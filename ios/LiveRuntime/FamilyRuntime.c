#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "FamilyRuntime.h"

#include <stdlib.h>
#include <string.h>

static PyObject *request_handler;

bool family_runtime_start(const char *python_home, const char *modules, const char *state) {
    if (!modules || !state || Py_IsInitialized()) return false;

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.install_signal_handlers = 0;
    config.site_import = 0;
    config.write_bytecode = 0;

    PyStatus status = PyStatus_Ok();
    if (python_home) status = PyConfig_SetBytesString(&config, &config.home, python_home);
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
        if (args) options = Py_BuildValue("{s:O}", "tcp_only", Py_True);
        if (options) result = PyObject_Call(initialize, args, options);
    }
    if (result) {
        PyObject *handler = PyObject_GetAttrString(backend, "request");
        if (handler && PyCallable_Check(handler)) {
            request_handler = handler;
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
