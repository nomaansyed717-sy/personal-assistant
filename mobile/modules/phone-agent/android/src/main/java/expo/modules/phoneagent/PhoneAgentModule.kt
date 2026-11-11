package expo.modules.phoneagent

import android.content.ComponentName
import android.content.Intent
import android.provider.Settings
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/** Bridges the Aide app's JavaScript to the accessibility service that operates other apps. */
class PhoneAgentModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("PhoneAgent")

    Events("onAgentEvent")

    OnCreate {
      AideAgentService.listener = { event -> sendEvent("onAgentEvent", event) }
    }

    OnDestroy {
      AideAgentService.listener = null
    }

    /** True when the user has switched on "Aide phone agent" in Android's accessibility settings. */
    Function("isEnabled") {
      if (AideAgentService.instance != null) return@Function true
      val context = appContext.reactContext ?: return@Function false
      val enabled = Settings.Secure.getString(context.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: ""
      val me = ComponentName(context, AideAgentService::class.java).flattenToString()
      enabled.split(':').any { it.equals(me, ignoreCase = true) }
    }

    /** Opens Android's accessibility settings so the user can switch the agent on (or off). */
    Function("openSettings") {
      val context = appContext.reactContext ?: return@Function false
      val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
      context.startActivity(intent)
      true
    }

    /** Starts a task the user asked for. Returns false if the service is off or a task is already running. */
    Function("start") { jobId: Int, goal: String, apiUrl: String, token: String ->
      val service = AideAgentService.instance ?: return@Function false
      service.start(AideAgentService.Job(jobId, goal, apiUrl.trimEnd('/'), token))
    }

    /** Continues after the user signed in, entered an OTP, answered a question or paid. */
    Function("resume") {
      AideAgentService.instance?.resume() ?: false
    }

    Function("stop") {
      AideAgentService.instance?.stop()
      true
    }

    Function("getState") {
      AideAgentService.instance?.state() ?: mapOf("running" to false, "jobId" to null, "goal" to null,
        "waitingFor" to null, "message" to "")
    }
  }
}
