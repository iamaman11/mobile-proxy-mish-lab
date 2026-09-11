package com.mobileproxymish.lab.devicefacts;

import android.app.Activity;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.Build;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

public final class MainActivity extends Activity {
    private static final String MODE_DEVICE_FACTS = "device_facts";
    private static final String MODE_NETWORK_BIND_MATRIX = "network_bind_matrix";

    static {
        System.loadLibrary("mishlabprobe");
    }

    private static native int[] nativeBindFresh(long networkHandle, int family);
    private static native int[] nativeBindFd(long networkHandle, int fd);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        writeResult();
        finish();
    }

    private void writeResult() {
        String mode = getIntent().getStringExtra("mish_lab_mode");
        if (mode == null || mode.isBlank()) {
            mode = MODE_DEVICE_FACTS;
        }

        boolean wifiPresent = false;
        boolean wifiValidated = false;
        boolean cellularPresent = false;
        boolean cellularValidated = false;
        boolean vpnPresent = false;
        Network directCellular = null;

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
                    boolean direct = validated
                            && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                            && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN);
                    if (directCellular == null && direct) {
                        directCellular = network;
                    }
                }
                if (caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) {
                    vpnPresent = true;
                }
            }
        }

        String abi = Build.SUPPORTED_ABIS.length > 0 ? Build.SUPPORTED_ABIS[0] : "UNKNOWN";
        JSONObject result = new JSONObject();
        try {
            result.put("status", "PASS");
            result.put("mode", mode);
            result.put("sdk", Build.VERSION.SDK_INT);
            result.put("abi", abi);
            result.put("wifi_present", wifiPresent);
            result.put("wifi_validated", wifiValidated);
            result.put("cellular_present", cellularPresent);
            result.put("cellular_validated", cellularValidated);
            result.put("vpn_present", vpnPresent);

            if (MODE_NETWORK_BIND_MATRIX.equals(mode)) {
                if (directCellular == null) {
                    result.put("status", "BLOCKED");
                    result.put("classification", "NO_VALIDATED_DIRECT_CELLULAR");
                    result.put("bind_matrix_complete", false);
                } else {
                    JSONObject cases = runBindMatrix(directCellular);
                    result.put("bind_matrix", cases);
                    result.put("bind_matrix_complete", true);
                    result.put("classification", classify(cases));
                }
            } else {
                result.put("classification", "DEVICE_FACTS");
            }
        } catch (JSONException failure) {
            throw new IllegalStateException("failed to build LAB result", failure);
        }

        File target = new File(getFilesDir(), "result.json");
        try (FileOutputStream out = new FileOutputStream(target, false)) {
            out.write(result.toString().getBytes(StandardCharsets.UTF_8));
            out.flush();
        } catch (Exception failure) {
            throw new IllegalStateException("failed to write LAB result", failure);
        }
    }

    private static JSONObject runBindMatrix(Network network) throws JSONException {
        JSONObject cases = new JSONObject();
        int[] families = {OsConstants.AF_INET, OsConstants.AF_INET6};
        String[] familyNames = {"ipv4", "ipv6"};
        for (int index = 0; index < families.length; index++) {
            int family = families[index];
            String familyName = familyNames[index];
            cases.put("framework_" + familyName + "_direct", frameworkBind(network, family, false));
            cases.put("ndk_" + familyName + "_direct", ndkBind(network, family, false));
            cases.put("framework_" + familyName + "_dup_adopt", frameworkBind(network, family, true));
            cases.put("ndk_" + familyName + "_dup_adopt", ndkBind(network, family, true));
        }
        return cases;
    }

    private static JSONObject frameworkBind(Network network, int family, boolean duplicate) throws JSONException {
        FileDescriptor source = null;
        ParcelFileDescriptor adopted = null;
        try {
            source = Os.socket(
                    family,
                    OsConstants.SOCK_STREAM | OsConstants.SOCK_CLOEXEC | OsConstants.SOCK_NONBLOCK,
                    OsConstants.IPPROTO_TCP);
            FileDescriptor target = source;
            if (duplicate) {
                ParcelFileDescriptor duplicateFd = ParcelFileDescriptor.dup(source);
                int detached = duplicateFd.detachFd();
                Os.close(source);
                source = null;
                adopted = ParcelFileDescriptor.adoptFd(detached);
                target = adopted.getFileDescriptor();
            }
            network.bindSocket(target);
            return caseResult(true, 0);
        } catch (Exception failure) {
            return caseResult(false, errnoOf(failure));
        } finally {
            if (adopted != null) {
                try {
                    adopted.close();
                } catch (Exception ignored) {
                    // Probe cleanup only.
                }
            }
            if (source != null) {
                try {
                    Os.close(source);
                } catch (Exception ignored) {
                    // Probe cleanup only.
                }
            }
        }
    }

    private static JSONObject ndkBind(Network network, int family, boolean duplicate) throws JSONException {
        int[] nativeResult;
        if (!duplicate) {
            nativeResult = nativeBindFresh(network.getNetworkHandle(), family);
        } else {
            FileDescriptor source = null;
            int detached = -1;
            try {
                source = Os.socket(
                        family,
                        OsConstants.SOCK_STREAM | OsConstants.SOCK_CLOEXEC | OsConstants.SOCK_NONBLOCK,
                        OsConstants.IPPROTO_TCP);
                ParcelFileDescriptor duplicateFd = ParcelFileDescriptor.dup(source);
                detached = duplicateFd.detachFd();
                Os.close(source);
                source = null;
                nativeResult = nativeBindFd(network.getNetworkHandle(), detached);
            } catch (Exception failure) {
                return caseResult(false, errnoOf(failure));
            } finally {
                if (source != null) {
                    try {
                        Os.close(source);
                    } catch (Exception ignored) {
                        // Probe cleanup only.
                    }
                }
                if (detached >= 0) {
                    try {
                        ParcelFileDescriptor.adoptFd(detached).close();
                    } catch (Exception ignored) {
                        // Probe cleanup only.
                    }
                }
            }
        }
        if (nativeResult == null || nativeResult.length != 2) {
            return caseResult(false, -1);
        }
        return caseResult(nativeResult[0] == 0, nativeResult[1]);
    }

    private static JSONObject caseResult(boolean pass, int errno) throws JSONException {
        JSONObject result = new JSONObject();
        result.put("result", pass ? "PASS" : "FAIL");
        result.put("errno", errno);
        return result;
    }

    private static int errnoOf(Throwable failure) {
        Throwable current = failure;
        while (current != null) {
            if (current instanceof ErrnoException) {
                return ((ErrnoException) current).errno;
            }
            current = current.getCause();
        }
        return 0;
    }

    private static boolean passed(JSONObject cases, String name) {
        JSONObject value = cases.optJSONObject(name);
        return value != null && "PASS".equals(value.optString("result"));
    }

    private static boolean all(JSONObject cases, String... names) {
        for (String name : names) {
            if (!passed(cases, name)) {
                return false;
            }
        }
        return true;
    }

    private static String classify(JSONObject cases) {
        String[] framework = {
                "framework_ipv4_direct", "framework_ipv6_direct",
                "framework_ipv4_dup_adopt", "framework_ipv6_dup_adopt"
        };
        String[] ndk = {
                "ndk_ipv4_direct", "ndk_ipv6_direct",
                "ndk_ipv4_dup_adopt", "ndk_ipv6_dup_adopt"
        };
        String[] direct = {
                "framework_ipv4_direct", "framework_ipv6_direct",
                "ndk_ipv4_direct", "ndk_ipv6_direct"
        };
        String[] duplicate = {
                "framework_ipv4_dup_adopt", "framework_ipv6_dup_adopt",
                "ndk_ipv4_dup_adopt", "ndk_ipv6_dup_adopt"
        };
        String[] ipv4 = {
                "framework_ipv4_direct", "ndk_ipv4_direct",
                "framework_ipv4_dup_adopt", "ndk_ipv4_dup_adopt"
        };
        String[] ipv6 = {
                "framework_ipv6_direct", "ndk_ipv6_direct",
                "framework_ipv6_dup_adopt", "ndk_ipv6_dup_adopt"
        };

        boolean frameworkAll = all(cases, framework);
        boolean ndkAll = all(cases, ndk);
        boolean directAll = all(cases, direct);
        boolean duplicateAll = all(cases, duplicate);
        boolean ipv4All = all(cases, ipv4);
        boolean ipv6All = all(cases, ipv6);

        if (frameworkAll && ndkAll) {
            return "ALL_BIND_PATHS_PASS";
        }
        if (frameworkAll && !ndkAll) {
            return "NDK_BIND_FAILURE";
        }
        if (!frameworkAll && ndkAll) {
            return "FRAMEWORK_BIND_FAILURE";
        }
        if (directAll && !duplicateAll) {
            return "DUP_ADOPT_FD_LIFECYCLE_FAILURE";
        }
        if (!directAll && duplicateAll) {
            return "DIRECT_FD_PATH_FAILURE";
        }
        if (ipv4All && !ipv6All) {
            return "IPV6_SPECIFIC_FAILURE";
        }
        if (!ipv4All && ipv6All) {
            return "IPV4_SPECIFIC_FAILURE";
        }
        return "MIXED_BIND_FAILURE";
    }
}
