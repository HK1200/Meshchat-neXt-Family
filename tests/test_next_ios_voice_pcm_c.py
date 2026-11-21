"""Compile and execute the actual C PCM boundary without a microphone or iPad.

The wrapper releases the caller's GIL, just as the native audio queue does.
Production's existing-interpreter initialization is retained, not called again.
"""
import importlib.util
from pathlib import Path
import subprocess
import sysconfig

import pytest
ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def pcm(tmp_path_factory):
    folder=tmp_path_factory.mktemp('voice-c-boundary')
    (folder/'Python').symlink_to(sysconfig.get_path('include'),target_is_directory=True)
    source=folder/'wrapper.c'
    production=str(ROOT/'ios/NextRuntimeProbe/App/ProbeRuntime.c').replace('\\','\\\\').replace('"','\\"')
    source.write_text('#include "'+production+'"\n'+r'''
static PyObject *test_exchange(PyObject *self, PyObject *args) {
    const char *id, *input; Py_ssize_t input_size, capacity;
    if (!PyArg_ParseTuple(args, "sy#n", &id, &input, &input_size, &capacity)) return NULL;
    if (capacity < 0 || capacity > 11520) return PyErr_Format(PyExc_ValueError, "Bad test capacity");
    uint8_t output[11520]; size_t count;
    Py_BEGIN_ALLOW_THREADS
    count = family_runtime_voice_exchange(id, (const uint8_t *)input, (size_t)input_size,
                                         true, output, (size_t)capacity);
    Py_END_ALLOW_THREADS
    return PyBytes_FromStringAndSize((const char *)output, (Py_ssize_t)count);
}
static PyObject *test_mute(PyObject *self, PyObject *args) {
    int muted;
    if (!PyArg_ParseTuple(args, "p", &muted)) return NULL;
    next_probe_set_voice_muted(muted != 0);
    Py_RETURN_NONE;
}
static PyMethodDef test_methods[] = {
    {"bind", voice_bind, METH_VARARGS, NULL},
    {"exchange", test_exchange, METH_VARARGS, NULL},
    {"mute", test_mute, METH_VARARGS, NULL},
    {NULL,NULL,0,NULL}
};
static struct PyModuleDef test_module = {PyModuleDef_HEAD_INIT,"_next_voice_pcm_test",NULL,-1,test_methods};
PyMODINIT_FUNC PyInit__next_voice_pcm_test(void) {
    atomic_store_explicit(&runtime_initialized, 1, memory_order_release);
    return PyModule_Create(&test_module);
}
''')
    output=folder/('_next_voice_pcm_test'+sysconfig.get_config_var('EXT_SUFFIX'))
    subprocess.run(['cc','-shared','-fPIC','-std=gnu11','-Werror=implicit-function-declaration',
        '-I'+str(folder),'-I'+sysconfig.get_path('include'),'-I'+str(ROOT/'ios/LiveRuntime'),
        '-I'+str(ROOT/'ios/NextRuntimeProbe/App'),str(source),'-o',str(output)],check=True,capture_output=True,timeout=30)
    spec=importlib.util.spec_from_file_location('_next_voice_pcm_test',output)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_native_queue_pushes_microphone_even_when_playback_is_full(pcm):
    pushed=[];pulled=[]
    pcm.bind(lambda *values:pushed.append(values),lambda identifier:pulled.append(identifier) or b'\x01\x00'*960)
    pcm.mute(False)
    assert pcm.exchange('a'*32,b'\x02\x00'*960,0)==b''
    assert pushed==[('a'*32,b'\x02\x00'*960,True)] and not pulled
    assert pcm.exchange('a'*32,b'',1920)==b'\x01\x00'*960
    assert pulled==['a'*32]


def test_native_mute_blocks_capture_immediately_but_keeps_receive_audio(pcm):
    pushed=[]
    pcm.bind(lambda *values:pushed.append(values),lambda identifier:b'\x01\x00'*960)
    pcm.mute(True)
    assert pcm.exchange('b'*32,b'\x02\x00'*960,1920)==b'\x01\x00'*960
    assert pushed==[]
    pcm.mute(False)
    assert pcm.exchange('b'*32,b'\x02\x00'*960,1920)==b'\x01\x00'*960
    assert len(pushed)==1


def test_invalid_ids_sizes_and_oversized_output_never_cross_the_boundary(pcm):
    pushed=[]
    pcm.bind(lambda *values:pushed.append(values),lambda identifier:b'\x01\x00'*2000)
    pcm.mute(False)
    for identifier,data,capacity in [('c'*31,b'xx',1920),('g'*32,b'xx',1920),
                                      ('c'*32,b'x',1920),('c'*32,b'x'*11522,1920),('c'*32,b'xx',100)]:
        assert pcm.exchange(identifier,data,capacity)==b''
    assert not pushed
    assert pcm.exchange('c'*32,b'',1920)==b''
    with pytest.raises(TypeError):pcm.bind(None,lambda _:b'')
