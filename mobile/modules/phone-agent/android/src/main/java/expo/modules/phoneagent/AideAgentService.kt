package expo.modules.phoneagent

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Color
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * Aide's phone agent. While a task the user started is running, it reads the screen, asks the Aide
 * server for the next step and carries it out in whatever app is open.
 *
 * Hard limits enforced here, on the phone, whatever the server says:
 *  - never types into password fields;
 *  - never taps, types or scrolls inside a payment app (UPI apps, wallets, banks);
 *  - stops and hands over to the user for logins, OTPs and payments;
 *  - shows a floating Stop button the whole time a task runs.
 */
class AideAgentService : AccessibilityService() {

  data class Job(val id: Int, val goal: String, val apiUrl: String, val token: String)

  companion object {
    private const val TAG = "AideAgent"
    private const val MAX_TURNS = 120
    private const val MAX_NODES = 220

    @Volatile var instance: AideAgentService? = null
    @Volatile var listener: ((Map<String, Any?>) -> Unit)? = null

    val PAYMENT_PACKAGES = setOf(
      "com.phonepe.app", "com.google.android.apps.nbu.paisa.user", "net.one97.paytm", "in.org.npci.upiapp",
      "in.amazon.mShop.android.shopping.upi", "com.mobikwik_new", "com.freecharge.android", "com.dreamplug.androidapp",
      "com.sbi.upi", "com.sbi.lotusintouch", "com.snapwork.hdfc", "com.csam.icici.bank.imobile", "com.axis.mobile",
      "com.msf.kbank.mobile", "com.bankofbaroda.mconnect", "com.infrasofttech.indianBank", "com.whatsapp.payments",
      "com.razorpay.payments.app", "com.paypal.android.p2pmobile"
    )
  }

  private val main = Handler(Looper.getMainLooper())
  private var worker: Thread? = null
  @Volatile private var stopRequested = false
  @Volatile var job: Job? = null
    private set
  @Volatile var waitingFor: String? = null
    private set
  @Volatile var lastMessage: String = ""
    private set
  @Volatile private var lastPackage: String? = null
  private var nodes = HashMap<Int, AccessibilityNodeInfo>()
  private var currentPackage: String = ""

  private var overlay: LinearLayout? = null
  private var overlayText: TextView? = null
  private var resumeButton: Button? = null

  // ------------------------------------------------------------------ lifecycle

  override fun onServiceConnected() {
    super.onServiceConnected()
    instance = this
    emit(mapOf("type" to "service", "enabled" to true))
  }

  override fun onAccessibilityEvent(event: AccessibilityEvent?) {}

  override fun onInterrupt() {}

  override fun onUnbind(intent: Intent?): Boolean {
    stopRequested = true
    instance = null
    main.post { removeOverlay() }
    emit(mapOf("type" to "service", "enabled" to false))
    return super.onUnbind(intent)
  }

  // ------------------------------------------------------------------ control (called from the module)

  fun isRunning(): Boolean = worker?.isAlive == true

  fun start(newJob: Job): Boolean {
    if (isRunning()) return false
    job = newJob
    waitingFor = null
    lastPackage = null
    begin(resume = false)
    return true
  }

  fun resume(): Boolean {
    if (isRunning() || job == null) return false
    begin(resume = true)
    return true
  }

  fun stop() {
    stopRequested = true
    if (!isRunning()) {
      job?.let { j -> thread { safePostEvent(j, "stopped", "Stopped by you") } }
      finishUi("Stopped")
      job = null
      waitingFor = null
    }
  }

  fun state(): Map<String, Any?> = mapOf(
    "running" to isRunning(),
    "jobId" to job?.id,
    "goal" to job?.goal,
    "waitingFor" to waitingFor,
    "message" to lastMessage
  )

  private fun begin(resume: Boolean) {
    stopRequested = false
    waitingFor = null
    main.post { showOverlay("Starting…", waiting = false) }
    worker = thread(name = "aide-agent") { runLoop(resume) }
  }

  // ------------------------------------------------------------------ the loop

  private fun runLoop(resume: Boolean) {
    val j = job ?: return
    var sendApps = true
    try {
      postEvent(j, if (resume) "resumed" else "started", "")
      emit(mapOf("type" to (if (resume) "resumed" else "started"), "jobId" to j.id))
      if (resume) lastPackage?.let { openApp(it) }
      for (turn in 0 until MAX_TURNS) {
        if (stopRequested) {
          postEvent(j, "stopped", "Stopped by you")
          emit(mapOf("type" to "stopped", "jobId" to j.id))
          finishUi("Stopped")
          job = null
          return
        }
        Thread.sleep(if (turn == 0) 400L else 900L)
        val screen = snapshot()
        val body = JSONObject().put("screen", screen)
        if (sendApps) {
          body.put("apps", installedApps())
          sendApps = false
        }
        val resp = request("POST", "${j.apiUrl}/api/phone/jobs/${j.id}/step", j.token, body)
        val action = resp.optString("action")
        val progress = resp.optString("progress", "")
        if (progress.isNotBlank()) {
          lastMessage = progress
          main.post { overlayText?.text = "Aide: $progress" }
        }
        emit(mapOf("type" to "step", "jobId" to j.id, "action" to action, "progress" to progress))
        when (action) {
          "tap" -> act(j, "tap") { tap(resp.optInt("node_id", -1)) }
          "type" -> act(j, "type") { type(resp.optInt("node_id", -1), resp.optString("text"), resp.optBoolean("submit")) }
          "scroll" -> act(j, "scroll") { scroll(resp.optString("direction", "down"), if (resp.has("node_id")) resp.optInt("node_id") else null) }
          "open_app" -> act(j, "open_app") { openApp(resp.optString("package")) }
          "back" -> performGlobalAction(GLOBAL_ACTION_BACK)
          "home" -> performGlobalAction(GLOBAL_ACTION_HOME)
          "wait" -> Thread.sleep((resp.optInt("seconds", 2).coerceIn(1, 10) * 1000).toLong())
          "need_user" -> {
            val reason = resp.optString("reason", "question")
            val message = resp.optString("message", "Your turn")
            waitingFor = reason
            lastMessage = message
            emit(mapOf("type" to "need_user", "jobId" to j.id, "reason" to reason, "message" to message))
            main.post { showOverlay(message, waiting = true) }
            return
          }
          "done", "stop" -> {
            val message = resp.optString("message", "Done")
            lastMessage = message
            emit(mapOf("type" to action, "jobId" to j.id, "message" to message))
            finishUi(if (action == "done") "Done" else "Stopped")
            job = null
            return
          }
          else -> Thread.sleep(1000)
        }
      }
      postEvent(j, "error", "Took too many steps")
      finishUi("Stopped")
      job = null
    } catch (e: Exception) {
      Log.w(TAG, "agent loop failed", e)
      safePostEvent(j, "error", e.message ?: "error")
      emit(mapOf("type" to "error", "jobId" to j.id, "message" to (e.message ?: "error")))
      finishUi("Stopped")
      job = null
    }
  }

  private fun act(j: Job, what: String, block: () -> Boolean) {
    val ok = try { block() } catch (e: Exception) { false }
    if (!ok) safePostEvent(j, "action_failed", "$what failed on $currentPackage")
  }

  // ------------------------------------------------------------------ reading the screen

  private fun snapshot(): JSONObject {
    nodes = HashMap()
    val root = rootInActiveWindow
    currentPackage = root?.packageName?.toString() ?: ""
    if (currentPackage.isNotEmpty() && currentPackage != packageName) lastPackage = currentPackage
    val list = JSONArray()
    if (root != null) walk(root, list, 0)
    val keyboard = try {
      windows.any { it.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD }
    } catch (e: Exception) { false }
    return JSONObject().put("package", currentPackage).put("nodes", list).put("keyboard", keyboard)
  }

  private fun walk(node: AccessibilityNodeInfo, out: JSONArray, depth: Int) {
    if (out.length() >= MAX_NODES || depth > 40) return
    if (node.isVisibleToUser) {
      val text = node.text?.toString()?.trim().orEmpty()
      val desc = node.contentDescription?.toString()?.trim().orEmpty()
      val useful = text.isNotEmpty() || desc.isNotEmpty() || node.isClickable || node.isEditable || node.isScrollable || node.isCheckable
      if (useful) {
        val id = nodes.size
        nodes[id] = node
        val r = Rect()
        node.getBoundsInScreen(r)
        val o = JSONObject()
          .put("id", id)
          .put("cls", node.className?.toString()?.substringAfterLast('.') ?: "")
          .put("text", if (node.isPassword) "" else text.take(160))
          .put("desc", if (node.isPassword) "" else desc.take(160))
          .put("rid", node.viewIdResourceName ?: "")
          .put("click", node.isClickable)
          .put("edit", node.isEditable)
          .put("scroll", node.isScrollable)
          .put("pwd", node.isPassword)
          .put("b", JSONArray(listOf(r.left, r.top, r.right, r.bottom)))
        if (node.isCheckable) o.put("check", node.isChecked)
        out.put(o)
      }
    }
    for (i in 0 until node.childCount) {
      val child = node.getChild(i) ?: continue
      walk(child, out, depth + 1)
    }
  }

  private fun installedApps(): JSONArray {
    val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
    val out = JSONArray()
    val seen = HashSet<String>()
    @Suppress("DEPRECATION")
    for (ri in packageManager.queryIntentActivities(intent, 0)) {
      val pkg = ri.activityInfo?.packageName ?: continue
      if (pkg == packageName || !seen.add(pkg)) continue
      out.put(JSONObject().put("label", ri.loadLabel(packageManager).toString()).put("package", pkg))
    }
    return out
  }

  // ------------------------------------------------------------------ acting

  private fun inPaymentApp(): Boolean = currentPackage in PAYMENT_PACKAGES

  private fun tap(id: Int): Boolean {
    if (inPaymentApp()) return false
    val node = nodes[id] ?: return false
    var n: AccessibilityNodeInfo? = node
    var hops = 0
    while (n != null && hops < 6) {
      if (n.isClickable && n.isEnabled) return n.performAction(AccessibilityNodeInfo.ACTION_CLICK)
      n = n.parent
      hops++
    }
    val r = Rect()
    node.getBoundsInScreen(r)
    return gesture(r.exactCenterX(), r.exactCenterY(), r.exactCenterX(), r.exactCenterY(), 60)
  }

  private fun type(id: Int, text: String, submit: Boolean): Boolean {
    if (inPaymentApp()) return false
    val node = nodes[id] ?: return false
    if (node.isPassword || !node.isEditable) return false // passwords are always the user's to type
    node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
    node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
    val args = Bundle()
    args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
    val ok = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
    if (ok && submit && Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
      Thread.sleep(250)
      node.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id)
    }
    return ok
  }

  private fun scroll(direction: String, id: Int?): Boolean {
    if (inPaymentApp()) return false
    val forward = direction == "down" || direction == "right"
    val target = id?.let { nodes[it] }?.let { findScrollable(it) } ?: nodes.values.firstOrNull { it.isScrollable }
    if (target != null) {
      val action = if (forward) AccessibilityNodeInfo.ACTION_SCROLL_FORWARD else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
      if (target.performAction(action)) return true
    }
    // Fall back to a swipe in the middle of the screen.
    val dm = resources.displayMetrics
    val cx = dm.widthPixels / 2f
    val cy = dm.heightPixels / 2f
    val dy = dm.heightPixels * 0.3f
    val dx = dm.widthPixels * 0.3f
    return when (direction) {
      "down" -> gesture(cx, cy + dy, cx, cy - dy, 350)
      "up" -> gesture(cx, cy - dy, cx, cy + dy, 350)
      "right" -> gesture(cx + dx, cy, cx - dx, cy, 300)
      else -> gesture(cx - dx, cy, cx + dx, cy, 300)
    }
  }

  private fun findScrollable(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
    var n: AccessibilityNodeInfo? = node
    var hops = 0
    while (n != null && hops < 8) {
      if (n.isScrollable) return n
      n = n.parent
      hops++
    }
    return null
  }

  private fun openApp(pkg: String): Boolean {
    if (pkg.isBlank() || pkg in PAYMENT_PACKAGES || pkg == packageName) return false
    val intent = packageManager.getLaunchIntentForPackage(pkg) ?: return false
    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    startActivity(intent)
    Thread.sleep(1500)
    return true
  }

  private fun gesture(x1: Float, y1: Float, x2: Float, y2: Float, durationMs: Long): Boolean {
    val path = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }
    val stroke = GestureDescription.StrokeDescription(path, 0, durationMs)
    val done = java.util.concurrent.CountDownLatch(1)
    var ok = false
    main.post {
      ok = dispatchGesture(GestureDescription.Builder().addStroke(stroke).build(), object : GestureResultCallback() {
        override fun onCompleted(gestureDescription: GestureDescription?) { done.countDown() }
        override fun onCancelled(gestureDescription: GestureDescription?) { ok = false; done.countDown() }
      }, null)
      if (!ok) done.countDown()
    }
    done.await(3, java.util.concurrent.TimeUnit.SECONDS)
    return ok
  }

  // ------------------------------------------------------------------ server

  private fun request(method: String, url: String, token: String, body: JSONObject?): JSONObject {
    val conn = URL(url).openConnection() as HttpURLConnection
    try {
      conn.requestMethod = method
      conn.connectTimeout = 20_000
      conn.readTimeout = 90_000
      conn.setRequestProperty("Authorization", "Bearer $token")
      conn.setRequestProperty("X-Requested-With", "aide")
      conn.setRequestProperty("Accept", "application/json")
      if (body != null) {
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/json")
        conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
      }
      val code = conn.responseCode
      val stream = if (code in 200..299) conn.inputStream else conn.errorStream
      val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
      if (code !in 200..299) throw IllegalStateException("Server said $code")
      return if (text.isBlank() || text == "null") JSONObject() else JSONObject(text)
    } finally {
      conn.disconnect()
    }
  }

  private fun postEvent(j: Job, type: String, detail: String) {
    request("POST", "${j.apiUrl}/api/phone/jobs/${j.id}/event", j.token, JSONObject().put("type", type).put("detail", detail))
  }

  private fun safePostEvent(j: Job, type: String, detail: String) {
    try { postEvent(j, type, detail) } catch (e: Exception) { Log.w(TAG, "event failed", e) }
  }

  private fun emit(event: Map<String, Any?>) {
    try { listener?.invoke(event) } catch (e: Exception) { Log.w(TAG, "listener failed", e) }
  }

  // ------------------------------------------------------------------ floating Stop / Resume bar

  private fun dp(v: Int): Int = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics).toInt()

  private fun pill(color: Int): GradientDrawable = GradientDrawable().apply {
    cornerRadius = dp(22).toFloat()
    setColor(color)
  }

  private fun showOverlay(message: String, waiting: Boolean) {
    if (overlay == null) {
      val wm = getSystemService(WINDOW_SERVICE) as WindowManager
      val bar = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        setPadding(dp(14), dp(8), dp(8), dp(8))
        background = pill(Color.parseColor("#F20E3B43"))
        elevation = dp(6).toFloat()
      }
      val label = TextView(this).apply {
        setTextColor(Color.WHITE)
        textSize = 13f
        maxLines = 3
        maxWidth = (resources.displayMetrics.widthPixels * 0.55).toInt()
      }
      val resume = Button(this).apply {
        setText("Resume")
        isAllCaps = false
        setTextColor(Color.parseColor("#2B1C02"))
        background = pill(Color.parseColor("#E8A33D"))
        setOnClickListener { resume() }
      }
      val stopBtn = Button(this).apply {
        setText("Stop")
        isAllCaps = false
        setTextColor(Color.WHITE)
        background = pill(Color.parseColor("#B4483C"))
        setOnClickListener { stop() }
      }
      val lp = { LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(40)).apply { marginStart = dp(8) } }
      bar.addView(label)
      bar.addView(resume, lp())
      bar.addView(stopBtn, lp())
      val params = WindowManager.LayoutParams(
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
        PixelFormat.TRANSLUCENT
      ).apply {
        gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
        y = dp(36)
      }
      try {
        wm.addView(bar, params)
        overlay = bar
        overlayText = label
        resumeButton = resume
      } catch (e: Exception) {
        Log.w(TAG, "overlay failed", e)
      }
    }
    overlayText?.text = if (waiting) "Your turn: $message" else "Aide: $message"
    resumeButton?.visibility = if (waiting) View.VISIBLE else View.GONE
  }

  private fun finishUi(word: String) {
    main.post {
      overlayText?.text = "Aide: $word"
      resumeButton?.visibility = View.GONE
    }
    main.postDelayed({ if (!isRunning() && waitingFor == null) removeOverlay() }, 2500)
  }

  private fun removeOverlay() {
    val o = overlay ?: return
    try { (getSystemService(WINDOW_SERVICE) as WindowManager).removeView(o) } catch (e: Exception) {}
    overlay = null
    overlayText = null
    resumeButton = null
  }
}
