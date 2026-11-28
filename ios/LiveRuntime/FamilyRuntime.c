#ifndef FAMILY_APP_STORE
#define FAMILY_APP_STORE 0
#endif
#define PY_SSIZE_T_CLEAN
#if defined(__APPLE__)
#include <TargetConditionals.h>
#endif
#if defined(TARGET_OS_IOS) && TARGET_OS_IOS
#include <Python/Python.h>
#else
#include <Python.h>
#endif

#include "FamilyRuntime.h"
#include "FamilyVoicePlayback.h"

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static PyObject *request_handler;
static PyObject *voice_push;
static PyObject *voice_pull;

static FamilyHTTPSPost https_post;

void family_runtime_set_https_post(FamilyHTTPSPost post) {
    if (!Py_IsInitialized()) https_post = post;
}

static PyObject *post_hint(PyObject *self, PyObject *args) {
    const char *url;
    const uint8_t *body;
    Py_ssize_t size;
    if (!PyArg_ParseTuple(args, "sy#", &url, &body, &size)) return NULL;
    if (size < 1 || size > 2048) return PyLong_FromLong(400);

    int32_t status;
    Py_BEGIN_ALLOW_THREADS
    status = https_post(url, body, (size_t)size);
    Py_END_ALLOW_THREADS
    return PyLong_FromLong(status);
}

static PyMethodDef https_methods[] = {
    {"post", post_hint, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef https_module = {
    PyModuleDef_HEAD_INIT, "_family_native_https", NULL, -1, https_methods
};

static PyObject *init_https(void) {
    return PyModule_Create(&https_module);
}

static FamilyBluetoothRequest bluetooth_request;

void family_runtime_set_bluetooth(FamilyBluetoothRequest request) {
    if (!Py_IsInitialized()) bluetooth_request = request;
}

static PyObject *bluetooth_call(PyObject *self, PyObject *args) {
    const char *request;
    if (!PyArg_ParseTuple(args, "s", &request)) return NULL;
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
    PyModuleDef_HEAD_INIT, "_family_bluetooth", NULL, -1, bluetooth_methods
};
static PyObject *init_bluetooth(void) { return PyModule_Create(&bluetooth_module); }

static FamilyInboxChanged inbox_changed;
void family_runtime_set_inbox_changed(FamilyInboxChanged callback) {
    if (!Py_IsInitialized()) inbox_changed = callback;
}
static PyObject *notify_inbox(PyObject *self, PyObject *ignored) {
    if (inbox_changed) {
        Py_BEGIN_ALLOW_THREADS
        inbox_changed();
        Py_END_ALLOW_THREADS
    }
    Py_RETURN_NONE;
}
static PyMethodDef inbox_methods[] = {
    {"inbox_changed", notify_inbox, METH_NOARGS, NULL},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef inbox_module = {
    PyModuleDef_HEAD_INIT, "_family_native_events", NULL, -1, inbox_methods
};
static PyObject *init_inbox(void) { return PyModule_Create(&inbox_module); }

/* Python may consume only the exact native-approved voice window. It cannot
 * create one or alter its lifetime through a JSON action or module method. */
static PyObject *consume_call_wake(PyObject *self, PyObject *args) {
    (void)self;
    const char *voice;
    if (!PyArg_ParseTuple(args, "s", &voice)) return NULL;
    bool allowed;
    Py_BEGIN_ALLOW_THREADS
    allowed = family_call_wake_consume(voice);
    Py_END_ALLOW_THREADS
    return PyBool_FromLong(allowed);
}
static PyMethodDef call_wake_methods[] = {
    {"consume", consume_call_wake, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef call_wake_module = {
    PyModuleDef_HEAD_INIT, "_family_native_calls", NULL, -1, call_wake_methods
};
static PyObject *init_call_wake(void) { return PyModule_Create(&call_wake_module); }

#if defined(TARGET_OS_IOS) && TARGET_OS_IOS
#define STRINGIFY_VALUE(value) #value
#define STRINGIFY(value) STRINGIFY_VALUE(value)
#define STDLIB_PATH "/lib/python" STRINGIFY(PY_MAJOR_VERSION) "." STRINGIFY(PY_MINOR_VERSION)

static PyStatus append_path(PyConfig *config, const char *home, const char *suffix) {
    size_t length = strlen(home) + strlen(suffix) + 1;
    char *path = malloc(length);
    if (!path) return PyStatus_NoMemory();
    snprintf(path, length, "%s%s", home, suffix);
    wchar_t *wide = Py_DecodeLocale(path, NULL);
    free(path);
    if (!wide) return PyStatus_Error("Invalid Python bundle path");
    PyStatus status = PyWideStringList_Append(&config->module_search_paths, wide);
    PyMem_RawFree(wide);
    return status;
}
#endif

bool family_runtime_start(const char *python_home, const char *modules, const char *state) {
    if (!modules || !state || Py_IsInitialized()) return false;
    if (PyImport_AppendInittab("_family_native_calls", init_call_wake) != 0) return false;
    if (https_post && PyImport_AppendInittab("_family_native_https", init_https) != 0) return false;
    if (inbox_changed && PyImport_AppendInittab("_family_native_events", init_inbox) != 0) return false;

    if (bluetooth_request && PyImport_AppendInittab("_family_bluetooth", init_bluetooth) != 0) return false;

    /* Keep Python's normal broken-pipe behavior without installing its other signal handlers. */
    if (signal(SIGPIPE, SIG_IGN) == SIG_ERR) return false;

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.install_signal_handlers = 0;
    config.site_import = 0;
    config.write_bytecode = 0;

    PyStatus status = PyStatus_Ok();
    if (python_home) status = PyConfig_SetBytesString(&config, &config.home, python_home);
#if defined(TARGET_OS_IOS) && TARGET_OS_IOS
    if (!python_home) status = PyStatus_Error("Missing bundled Python home");
    config.module_search_paths_set = 1;
    if (!PyStatus_Exception(status)) status = append_path(&config, python_home, STDLIB_PATH);
    if (!PyStatus_Exception(status)) status = append_path(&config, python_home, STDLIB_PATH "/lib-dynload");
#endif
    if (!PyStatus_Exception(status)) status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) return false;

    PyObject *path = PyUnicode_DecodeFSDefault(modules);
    PyObject *sys_path = PySys_GetObject("path");
    PyObject *backend = NULL;
    PyObject *initialize = NULL;
    PyObject *args = NULL;
    PyObject *options = NULL;
    PyObject *result = NULL;
    if (path && sys_path && PyList_Insert(sys_path, 0, path) == 0) {
        backend = PyImport_ImportModule("family_backend");
    }
    if (backend) initialize = PyObject_GetAttrString(backend, "initialize");
    if (initialize) {
        PyObject *state_path = PyUnicode_DecodeFSDefault(state);
        if (state_path) args = PyTuple_Pack(1, state_path);
        Py_XDECREF(state_path);
        if (args) {
#if defined(TARGET_OS_IOS) && TARGET_OS_IOS
            options = Py_BuildValue("{s:O,s:O}", "tcp_only", Py_True, "ios_voice", Py_True);
#else
            options = Py_BuildValue("{s:O}", "tcp_only", Py_True);
#endif
        }
        if (options && PyDict_SetItemString(options, "store_build", FAMILY_APP_STORE ? Py_True : Py_False) == 0)
            result = PyObject_Call(initialize, args, options);
    }
    if (result) {
        PyObject *handler = PyObject_GetAttrString(backend, "request");
        if (handler && PyCallable_Check(handler)) {
            request_handler = handler;
            voice_push = PyObject_GetAttrString(backend, "voice_push");
            voice_pull = PyObject_GetAttrString(backend, "voice_pull");
        } else {
            Py_XDECREF(handler);
        }
    }
    Py_XDECREF(result);
    Py_XDECREF(options);
    Py_XDECREF(args);
    Py_XDECREF(initialize);
    Py_XDECREF(backend);
    Py_XDECREF(path);
    PyErr_Clear();

    /* Reticulum owns worker threads for the app lifetime. Leave the interpreter running. */
    PyEval_SaveThread();
    return request_handler != NULL;
}

char *family_runtime_request(const char *json) {
    if (!request_handler || !json) return NULL;

    PyGILState_STATE gil = PyGILState_Ensure();
    PyObject *input = PyUnicode_FromString(json);
    PyObject *result = input ? PyObject_CallOneArg(request_handler, input) : NULL;
    char *copy = NULL;
    if (result && PyUnicode_Check(result)) {
        Py_ssize_t size;
        const char *utf8 = PyUnicode_AsUTF8AndSize(result, &size);
        if (utf8) {
            copy = malloc((size_t)size + 1);
            if (copy) memcpy(copy, utf8, (size_t)size + 1);
        }
    }
    Py_XDECREF(result);
    Py_XDECREF(input);
    PyErr_Clear();
    PyGILState_Release(gil);
    return copy;
}

size_t family_runtime_voice_exchange(const char *call_id, const uint8_t *input,
                                     size_t input_size, bool native_processing, uint8_t *output, size_t capacity) {
    if (!call_id || !voice_push || !voice_pull || !output || input_size > 11520) return 0;
    PyGILState_STATE gil = PyGILState_Ensure();
    PyObject *id = PyUnicode_FromString(call_id);
    size_t count = 0;
    if (id && input && input_size) {
        PyObject *bytes = PyBytes_FromStringAndSize((const char *)input, (Py_ssize_t)input_size);
        PyObject *processed = native_processing ? Py_True : Py_False;
        PyObject *pushed = bytes ? PyObject_CallFunctionObjArgs(voice_push, id, bytes, processed, NULL) : NULL;
        Py_XDECREF(pushed);
        Py_XDECREF(bytes);
        PyErr_Clear();
    }
    count = family_voice_pull_frames(id, voice_pull, output, capacity);
    Py_XDECREF(id);
    PyErr_Clear();
    PyGILState_Release(gil);
    return count;
}
