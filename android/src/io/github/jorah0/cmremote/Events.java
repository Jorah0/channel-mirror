package io.github.jorah0.cmremote;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.os.Build;

/** The system's news for this app: it was updated (open it again), or how an update's install went. Not exported:
 * only the system (MY_PACKAGE_REPLACED) and this app's own PendingIntent (INSTALL) reach it. */
public class Events extends BroadcastReceiver {
    static final String INSTALL = "io.github.jorah0.cmremote.INSTALL";

    @Override
    public void onReceive(Context c, Intent i) {
        if (Intent.ACTION_MY_PACKAGE_REPLACED.equals(i.getAction())) {  // updated: start again (Android 10+ may not
            try {                                                          // allow it from here - then it's the icon)
                c.startActivity(new Intent(c, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            } catch (RuntimeException e) {
                // not allowed to start from the background: the user opens it
            }
            return;
        }
        if (!INSTALL.equals(i.getAction())) {
            return;
        }
        int status = i.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {  // Android asks the user first (the first update,
            Intent ask = Build.VERSION.SDK_INT >= 33                   // or before Android 12)
                    ? i.getParcelableExtra(Intent.EXTRA_INTENT, Intent.class) : i.getParcelableExtra(Intent.EXTRA_INTENT);
            if (ask != null && "android.content.pm.action.CONFIRM_INSTALL".equals(ask.getAction())) {
                try {
                    c.startActivity(ask.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                    MainActivity.say("progress", "Android asks you to confirm the update.");
                } catch (RuntimeException e) {
                    MainActivity.say("error", "Android's confirmation couldn't open - press Check for updates again.");
                }
            }
        } else if (status != PackageInstaller.STATUS_SUCCESS) {
            String why = i.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
            MainActivity.say("error", "The update wasn't installed" + (why != null ? ": " + why : "."));
        }
    }
}
