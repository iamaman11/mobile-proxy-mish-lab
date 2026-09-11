package com.mobileproxymish.lab.devicefacts;

import android.app.Activity;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.Build;
import android.os.Bundle;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

public final class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        writeResult();
        finish();
    }

    private void writeResult() {
        boolean wifiPresent = false;
        boolean wifiValidated = false;
        boolean cellularPresent = false;
        boolean cellularValidated = false;
        boolean vpnPresent = false;

        ConnectivityManager cm = getSystemService(ConnectivityManager.class);
        if (cm != null) {
            for (Network network : cm.getAllNetworks()) {
                NetworkCapabilities caps = cm.getNetworkCapabilities(network);
                if (caps == null) {
                    continue;
                }
                boolean validated = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED);
                if (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
                    wifiPresent = true;
                    wifiValidated |= validated;
                }
                if (caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)) {
                    cellularPresent = true;
                    cellularValidated |= validated;
                }
                if (caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) {
                    vpnPresent = true;
                }
            }
        }

        String abi = Build.SUPPORTED_ABIS.length > 0 ? Build.SUPPORTED_ABIS[0] : "UNKNOWN";
        String json = "{" +
            "\"status\":\"PASS\"," +
            "\"sdk\":" + Build.VERSION.SDK_INT + "," +
            "\"abi\":\"" + escape(abi) + "\"," +
            "\"wifi_present\":" + wifiPresent + "," +
            "\"wifi_validated\":" + wifiValidated + "," +
            "\"cellular_present\":" + cellularPresent + "," +
            "\"cellular_validated\":" + cellularValidated + "," +
            "\"vpn_present\":" + vpnPresent +
            "}";

        File target = new File(getFilesDir(), "result.json");
        try (FileOutputStream out = new FileOutputStream(target, false)) {
            out.write(json.getBytes(StandardCharsets.UTF_8));
            out.flush();
        } catch (Exception failure) {
            throw new IllegalStateException("failed to write LAB result", failure);
        }
    }

    private static String escape(String value) {
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
