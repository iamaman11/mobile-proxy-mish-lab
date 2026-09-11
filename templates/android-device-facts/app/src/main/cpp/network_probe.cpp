#include <jni.h>

#include <android/multinetwork.h>
#include <cerrno>
#include <cstdint>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

namespace {

jintArray make_result(JNIEnv* env, int rc, int error_number) {
    jint values[2] = {static_cast<jint>(rc), static_cast<jint>(error_number)};
    jintArray result = env->NewIntArray(2);
    if (result != nullptr) {
        env->SetIntArrayRegion(result, 0, 2, values);
    }
    return result;
}

jintArray bind_fd(JNIEnv* env, jlong network_handle, int fd) {
    errno = 0;
    const int rc = android_setsocknetwork(static_cast<net_handle_t>(network_handle), fd);
    const int error_number = rc == 0 ? 0 : errno;
    return make_result(env, rc, error_number);
}

}  // namespace

extern "C" JNIEXPORT jintArray JNICALL
Java_com_mobileproxymish_lab_devicefacts_MainActivity_nativeBindFresh(
        JNIEnv* env,
        jclass,
        jlong network_handle,
        jint family) {
    errno = 0;
    const int fd = socket(
            static_cast<int>(family),
            SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK,
            IPPROTO_TCP);
    if (fd < 0) {
        return make_result(env, -1, errno);
    }

    jintArray result = bind_fd(env, network_handle, fd);
    close(fd);
    return result;
}

extern "C" JNIEXPORT jintArray JNICALL
Java_com_mobileproxymish_lab_devicefacts_MainActivity_nativeBindFd(
        JNIEnv* env,
        jclass,
        jlong network_handle,
        jint fd) {
    return bind_fd(env, network_handle, static_cast<int>(fd));
}
