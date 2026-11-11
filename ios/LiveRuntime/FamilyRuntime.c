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

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static PyObject *request_handler;
static PyObject *voice_push;
static PyObject *voice_pull;

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
        if (options) result = PyObject_Call(initialize, args, options);
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
                                     size_t input_size, uint8_t *output, size_t capacity) {
    if (!call_id || !voice_push || !voice_pull || !output || input_size > 11520) return 0;
    PyGILState_STATE gil = PyGILState_Ensure();
    PyObject *id = PyUnicode_FromString(call_id);
    size_t count = 0;
    if (id && input && input_size) {
        PyObject *bytes = PyBytes_FromStringAndSize((const char *)input, (Py_ssize_t)input_size);
        PyObject *pushed = bytes ? PyObject_CallFunctionObjArgs(voice_push, id, bytes, NULL) : NULL;
        Py_XDECREF(pushed);
        Py_XDECREF(bytes);
        PyErr_Clear();
    }
    PyObject *received = id && capacity ? PyObject_CallOneArg(voice_pull, id) : NULL;
    if (received && PyBytes_Check(received)) {
        char *bytes;
        Py_ssize_t size;
        if (PyBytes_AsStringAndSize(received, &bytes, &size) == 0 && size >= 0 && (size_t)size <= capacity) {
            memcpy(output, bytes, (size_t)size);
            count = (size_t)size;
        }
    }
    Py_XDECREF(received);
    Py_XDECREF(id);
    PyErr_Clear();
    PyGILState_Release(gil);
    return count;
}
