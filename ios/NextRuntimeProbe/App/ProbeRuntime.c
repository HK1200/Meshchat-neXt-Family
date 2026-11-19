#define PY_SSIZE_T_CLEAN
#include <Python/Python.h>
#include "ProbeRuntime.h"
#include <stdio.h>

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
