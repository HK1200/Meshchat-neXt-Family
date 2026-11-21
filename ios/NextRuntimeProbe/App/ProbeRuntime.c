#define PY_SSIZE_T_CLEAN
#include <Python/Python.h>
#include "ProbeRuntime.h"
#include "ProbeSignals.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>

static _Atomic unsigned long listener_generation;
static _Atomic int runtime_initialized;
static _Atomic bool voice_muted;
void next_probe_set_voice_muted(bool muted) { atomic_store_explicit(&voice_muted, muted, memory_order_release); }
void next_probe_request_listener_recovery(void) {
    atomic_fetch_add_explicit(&listener_generation, 1, memory_order_relaxed);
}
unsigned long next_probe_listener_generation(void) {
    return atomic_load_explicit(&listener_generation, memory_order_relaxed);
}
static PyObject *lifecycle_generation(PyObject *self, PyObject *args) {
    return PyLong_FromUnsignedLong(next_probe_listener_generation());
}
static PyMethodDef lifecycle_methods[] = {
    {"generation", lifecycle_generation, METH_NOARGS, NULL},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef lifecycle_module = {
    PyModuleDef_HEAD_INIT, "_next_lifecycle", NULL, -1, lifecycle_methods,
    NULL, NULL, NULL, NULL
};
static PyObject *init_lifecycle(void) { return PyModule_Create(&lifecycle_module); }

static NextBluetoothRequest bluetooth_request;
static NextBluetoothRequest credentials_request;
static NextBluetoothRequest sip_request;
static NextBluetoothRequest voice_request;
static PyObject *voice_push, *voice_pull;

void next_probe_set_voice(NextBluetoothRequest request) {
    if (!Py_IsInitialized()) voice_request = request;
}

static PyObject *voice_call(PyObject *self, PyObject *args) {
    const char *request;
    if (!PyArg_ParseTuple(args, "s", &request)) return NULL;
    if (!voice_request) return PyErr_Format(PyExc_RuntimeError, "Native Reticulum calling is unavailable");
    char *reply;
    Py_BEGIN_ALLOW_THREADS
    reply = voice_request(request);
    Py_END_ALLOW_THREADS
    if (!reply) return PyErr_NoMemory();
    PyObject *result = PyUnicode_FromString(reply);
    free(reply);
    return result;
}

static PyObject *voice_bind(PyObject *self, PyObject *args) {
    PyObject *push, *pull;
    if (!PyArg_ParseTuple(args, "OO", &push, &pull)) return NULL;
    if (!PyCallable_Check(push) || !PyCallable_Check(pull))
        return PyErr_Format(PyExc_TypeError, "PCM callbacks must be callable");
    Py_INCREF(push); Py_INCREF(pull);
    Py_XDECREF(voice_push); Py_XDECREF(voice_pull);
    voice_push = push; voice_pull = pull;
    Py_RETURN_NONE;
}

static PyMethodDef voice_methods[] = {
    {"request", voice_call, METH_VARARGS, NULL},
    {"bind", voice_bind, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef voice_module = {
    PyModuleDef_HEAD_INIT, "_next_voice", NULL, -1, voice_methods,
    NULL, NULL, NULL, NULL
};
static PyObject *init_voice(void) { return PyModule_Create(&voice_module); }

size_t family_runtime_voice_exchange(const char *call_id, const uint8_t *input,
                                     size_t input_size, bool native_processing,
                                     uint8_t *output, size_t capacity) {
    if (!call_id || !output || strlen(call_id) != 32 || input_size > 11520 || input_size % 2 || (capacity != 0 && capacity < 1920) ||
        !atomic_load_explicit(&runtime_initialized, memory_order_acquire)) return 0;
    for (size_t index = 0; index < 32; index++) {
        char c = call_id[index];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return 0;
    }
    PyGILState_STATE gil = PyGILState_Ensure();
    if (!voice_push || !voice_pull) { PyGILState_Release(gil); return 0; }
    PyObject *identifier = PyUnicode_FromString(call_id);
    size_t count = 0;
    if (identifier && input && input_size && !atomic_load_explicit(&voice_muted, memory_order_acquire)) {
        PyObject *pcm = PyBytes_FromStringAndSize((const char *)input, (Py_ssize_t)input_size);
        PyObject *pushed = pcm ? PyObject_CallFunctionObjArgs(voice_push, identifier, pcm,
                                            native_processing ? Py_True : Py_False, NULL) : NULL;
        Py_XDECREF(pushed); Py_XDECREF(pcm); PyErr_Clear();
    }
    PyObject *received = identifier && capacity ? PyObject_CallOneArg(voice_pull, identifier) : NULL;
    if (received && PyBytes_Check(received)) {
        char *pcm; Py_ssize_t size;
        if (!PyBytes_AsStringAndSize(received, &pcm, &size) && size >= 0 && (size_t)size <= capacity) {
            memcpy(output, pcm, (size_t)size); count = (size_t)size;
        }
    }
    Py_XDECREF(received); Py_XDECREF(identifier); PyErr_Clear();
    PyGILState_Release(gil);
    return count;
}


void next_probe_set_sip(NextBluetoothRequest request) {
    if (!Py_IsInitialized()) sip_request = request;
}

void next_probe_set_credentials(NextBluetoothRequest request) {
    if (!Py_IsInitialized()) credentials_request = request;
}

void next_probe_set_bluetooth(NextBluetoothRequest request) {
    if (!Py_IsInitialized()) bluetooth_request = request;
}

static PyObject *bluetooth_call(PyObject *self, PyObject *args) {
    const char *request;
    if (!PyArg_ParseTuple(args, "s", &request)) return NULL;
    if (!bluetooth_request) return PyErr_Format(PyExc_RuntimeError, "Bluetooth is unavailable");
    char *reply;
    Py_BEGIN_ALLOW_THREADS
    reply = bluetooth_request(request);
    Py_END_ALLOW_THREADS
    if (!reply) return PyErr_NoMemory();
    PyObject *result = PyUnicode_FromString(reply);
    free(reply);
    return result;
}

static PyMethodDef bluetooth_methods[] = {
    {"request", bluetooth_call, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef bluetooth_module = {
    PyModuleDef_HEAD_INIT, "_family_bluetooth", NULL, -1, bluetooth_methods,
    NULL, NULL, NULL, NULL
};
static PyObject *init_bluetooth(void) { return PyModule_Create(&bluetooth_module); }

static PyObject *credentials_call(PyObject *self, PyObject *args) {
    const char *request;
    if (!PyArg_ParseTuple(args, "s", &request)) return NULL;
    if (!credentials_request) return PyErr_Format(PyExc_RuntimeError, "Secure credentials are unavailable");
    char *reply;
    Py_BEGIN_ALLOW_THREADS
    reply = credentials_request(request);
    Py_END_ALLOW_THREADS
    if (!reply) return PyErr_NoMemory();
    PyObject *result = PyUnicode_FromString(reply);
    free(reply);
    return result;
}

static PyMethodDef credentials_methods[] = {
    {"request", credentials_call, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef credentials_module = {
    PyModuleDef_HEAD_INIT, "_next_credentials", NULL, -1, credentials_methods,
    NULL, NULL, NULL, NULL
};
static PyObject *init_credentials(void) { return PyModule_Create(&credentials_module); }

static PyObject *sip_call(PyObject *self, PyObject *args) {
    const char *request;
    if (!PyArg_ParseTuple(args, "s", &request)) return NULL;
    if (!sip_request) return PyErr_Format(PyExc_RuntimeError, "Native SIP registration is unavailable");
    char *reply;
    Py_BEGIN_ALLOW_THREADS
    reply = sip_request(request);
    Py_END_ALLOW_THREADS
    if (!reply) return PyErr_NoMemory();
    PyObject *result = PyUnicode_FromString(reply);
    free(reply);
    return result;
}

static PyMethodDef sip_methods[] = {
    {"request", sip_call, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef sip_module = {
    PyModuleDef_HEAD_INIT, "_next_sip", NULL, -1, sip_methods,
    NULL, NULL, NULL, NULL
};
static PyObject *init_sip(void) { return PyModule_Create(&sip_module); }

static PyStatus append_bundle_path(PyConfig *config, const char *home, const char *suffix) {
    char path[4096];
    int length = snprintf(path, sizeof(path), "%s/%s", home, suffix);
    if (length < 0 || (size_t)length >= sizeof(path)) return PyStatus_Error("Path too long");
    wchar_t *wide = Py_DecodeLocale(path, NULL);
    if (!wide) return PyStatus_NoMemory();
    PyStatus status = PyWideStringList_Append(&config->module_search_paths, wide);
    PyMem_RawFree(wide);
    return status;
}

void next_probe_run(const char *home, const char *modules, const char *ready_file) {
    if (!next_prepare_process_signals()) {
        fprintf(stderr, "Could not configure safe TCP write handling\n");
        return;
    }
    if (PyImport_AppendInittab("_family_bluetooth", init_bluetooth) != 0) return;
    if (PyImport_AppendInittab("_next_credentials", init_credentials) != 0) return;
    if (PyImport_AppendInittab("_next_sip", init_sip) != 0) return;
    if (PyImport_AppendInittab("_next_voice", init_voice) != 0) return;
    if (PyImport_AppendInittab("_next_lifecycle", init_lifecycle) != 0) return;
    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.install_signal_handlers = 0;
    config.site_import = 0;
    config.write_bytecode = 0;
    config.module_search_paths_set = 1;
    PyStatus status = PyConfig_SetBytesString(&config, &config.home, home);
    if (!PyStatus_Exception(status)) status = append_bundle_path(&config, home, "lib/python3.14");
    if (!PyStatus_Exception(status)) status = append_bundle_path(&config, home, "lib/python3.14/lib-dynload");
    if (!PyStatus_Exception(status)) status = append_bundle_path(&config, modules, ".");
    if (!PyStatus_Exception(status)) status = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(status)) {
        fprintf(stderr, "Python initialization failed: %s\n", status.err_msg ?: "unknown error");
        PyConfig_Clear(&config);
        return;
    }
    PyConfig_Clear(&config);
    atomic_store_explicit(&runtime_initialized, 1, memory_order_release);
    PyObject *module = PyImport_ImportModule("loopback_probe");
    PyObject *entry = module ? PyObject_GetAttrString(module, "run_for_app") : NULL;
    PyObject *path = entry ? PyUnicode_DecodeFSDefault(ready_file) : NULL;
    PyObject *result = path ? PyObject_CallOneArg(entry, path) : NULL;
    if (!result) PyErr_Print();
    Py_XDECREF(result);
    Py_XDECREF(path);
    Py_XDECREF(entry);
    Py_XDECREF(module);
}

/* Called only by the native synthetic codec test, away from the main thread.
 * Keep it within this interpreter; never initialize a second Python runtime. */
char *next_probe_check_voice_codecs(void) {
    if (!atomic_load_explicit(&runtime_initialized, memory_order_acquire)) return NULL;
    PyGILState_STATE gil = PyGILState_Ensure();
    PyObject *module = PyImport_ImportModule("voice_codec_probe");
    PyObject *entry = module ? PyObject_GetAttrString(module, "run_json") : NULL;
    PyObject *result = entry ? PyObject_CallNoArgs(entry) : NULL;
    const char *json = result ? PyUnicode_AsUTF8(result) : NULL;
    char *reply = json ? strdup(json) : strdup("{\"ok\":false,\"error\":\"Bundled LXST codec check failed\"}");
    if (PyErr_Occurred()) PyErr_Print();
    Py_XDECREF(result);
    Py_XDECREF(entry);
    Py_XDECREF(module);
    PyGILState_Release(gil);
    return reply;
}
