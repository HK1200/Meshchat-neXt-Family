#define PY_SSIZE_T_CLEAN
#include <Python/Python.h>
#include "ProbeRuntime.h"
#include "ProbeSignals.h"
#include <stdio.h>
#include <stdlib.h>

static NextBluetoothRequest bluetooth_request;

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
