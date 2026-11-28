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
static int32_t test_https(const char *url, const uint8_t *body, size_t count) {
    return !PyGILState_Check() && strcmp(url, "https://example.invalid/v1/mailbox-alert") == 0 &&
        count == 2 && memcmp(body, "{}", 2) == 0 ? 204 : 500;
}
static PyMethodDef test_methods[] = {
    {"post", post_hint, METH_VARARGS, NULL},
    {"bind", voice_bind, METH_VARARGS, NULL},
    {"exchange", test_exchange, METH_VARARGS, NULL},
    {"mute", test_mute, METH_VARARGS, NULL},
    {NULL,NULL,0,NULL}
};
static struct PyModuleDef test_module = {PyModuleDef_HEAD_INIT,"_next_voice_pcm_test",NULL,-1,test_methods};
PyMODINIT_FUNC PyInit__next_voice_pcm_test(void) {
    https_post = test_https;
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


def test_native_hint_boundary_releases_interpreter_and_rejects_unbounded_requests(pcm):
    assert pcm.post('https://example.invalid/v1/mailbox-alert', b'{}') == 204
    for address, body in [('http://example.invalid', b'{}'), ('https://example.invalid', b''),
                          ('https://example.invalid', b'x' * 2049)]:
        assert pcm.post(address, body) == 400



@pytest.fixture(scope='module')
def family_pcm(tmp_path_factory):
    folder=tmp_path_factory.mktemp('family-voice-c-boundary')
    source=folder/'wrapper.c'
    production=str(ROOT/'ios/LiveRuntime/FamilyRuntime.c').replace('\\','\\\\').replace('"','\\"')
    source.write_text('#include "'+production+'"\n'+r"""
static PyObject *test_bind(PyObject *self, PyObject *args) {
    PyObject *push, *pull;
    if (!PyArg_ParseTuple(args,"OO",&push,&pull)) return NULL;
    if (!PyCallable_Check(push) || !PyCallable_Check(pull))
        return PyErr_Format(PyExc_TypeError,"Use callable PCM endpoints");
    Py_INCREF(push); Py_INCREF(pull);
    Py_XDECREF(voice_push); Py_XDECREF(voice_pull);
    voice_push=push; voice_pull=pull;
    Py_RETURN_NONE;
}
static PyObject *test_exchange(PyObject *self, PyObject *args) {
    const char *id, *input; Py_ssize_t input_size, capacity;
    if (!PyArg_ParseTuple(args,"sy#n",&id,&input,&input_size,&capacity)) return NULL;
    if (capacity<0 || capacity>11520) return PyErr_Format(PyExc_ValueError,"Bad test capacity");
    uint8_t output[11520]; size_t count;
    Py_BEGIN_ALLOW_THREADS
    count=family_runtime_voice_exchange(id,(const uint8_t *)input,(size_t)input_size,true,
                                       output,(size_t)capacity);
    Py_END_ALLOW_THREADS
    return PyBytes_FromStringAndSize((const char *)output,(Py_ssize_t)count);
}
static PyObject *test_mute(PyObject *self, PyObject *args) {
    /* Family enforces mute in its Python voice controller; tests only unmute. */
    int muted;
    if (!PyArg_ParseTuple(args,"p",&muted)) return NULL;
    if (muted) return PyErr_Format(PyExc_ValueError,"Test Family mute in its controller");
    Py_RETURN_NONE;
}
static PyMethodDef methods[]={
    {"bind",test_bind,METH_VARARGS,NULL},{"exchange",test_exchange,METH_VARARGS,NULL},
    {"mute",test_mute,METH_VARARGS,NULL},{NULL,NULL,0,NULL}
};
static struct PyModuleDef module={PyModuleDef_HEAD_INIT,"_family_voice_pcm_test",NULL,-1,methods};
PyMODINIT_FUNC PyInit__family_voice_pcm_test(void) { return PyModule_Create(&module); }
""")
    output=folder/('_family_voice_pcm_test'+sysconfig.get_config_var('EXT_SUFFIX'))
    subprocess.run(['cc','-shared','-fPIC','-std=gnu11','-Werror=implicit-function-declaration',
        '-I'+sysconfig.get_path('include'),'-I'+str(ROOT/'ios/LiveRuntime'),
        str(source),str(ROOT/'ios/LiveRuntime/FamilyCallWakeGate.c'),'-lpthread','-o',str(output)],
        check=True,capture_output=True,timeout=30)
    spec=importlib.util.spec_from_file_location('_family_voice_pcm_test',output)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module',params=['pcm','family_pcm'],ids=['next','family'])
def playback_pcm(request):
    return request.getfixturevalue(request.param)

def test_delayed_timer_drains_available_playback_slots_in_order(playback_pcm):
    from collections import deque
    frames=[bytes([n,0])*960 for n in (1,2,3)]
    queued=deque(frames)
    pushed=[]
    playback_pcm.bind(lambda *values:pushed.append(values),lambda _:queued.popleft() if queued else b'')
    playback_pcm.mute(False)
    capture=b'\x04\x00'*960
    assert playback_pcm.exchange('d'*32,capture,5760)==b''.join(frames)
    assert not queued
    assert pushed==[('d'*32,capture,True)]


@pytest.mark.parametrize('capacity,frames',[(1920,1),(3840,2),(5760,3),(11520,3)])
def test_playback_batch_never_exceeds_available_slots_or_sixty_ms(playback_pcm,capacity,frames):
    pulled=[]
    playback_pcm.bind(lambda *_:None,lambda identifier:pulled.append(identifier) or b'\x05\x00'*960)
    assert playback_pcm.exchange('e'*32,b'',capacity)==b'\x05\x00'*(960*frames)
    assert len(pulled)==frames


def test_playback_batch_stops_when_the_live_inbox_is_empty(playback_pcm):
    from collections import deque
    frames=deque([b'\x06\x00'*960,b''])
    pulled=[]
    def receive(identifier):
        pulled.append(identifier)
        return frames.popleft()
    playback_pcm.bind(lambda *_:None,receive)
    assert playback_pcm.exchange('f'*32,b'',5760)==b'\x06\x00'*960
    assert len(pulled)==2 and not frames


@pytest.mark.parametrize('data',[b'x'*960,b'x'*1921,b'x'*3840,None],ids=['short','odd','oversize','nonbytes'])
def test_playback_batch_rejects_incomplete_or_invalid_pcm_frames(playback_pcm,data):
    pulled=[]
    playback_pcm.bind(lambda *_:None,lambda identifier:pulled.append(identifier) or data)
    assert playback_pcm.exchange('a'*32,b'',5760)==b''
    assert len(pulled)==1


@pytest.mark.parametrize("bridge", ["pcm", "family_pcm"])
def test_ready_playback_can_be_scheduled_before_capture_encoding(request, bridge):
    boundary = request.getfixturevalue(bridge)
    frames = [bytes([value, 0]) * 960 for value in (1, 2, 3)]
    received = list(frames)
    scheduled = []
    pushes = []
    def encode(identifier, microphone, processed):
        assert scheduled == frames, "Ready speaker audio must precede potentially slow encoding"
        pushes.append((identifier, microphone, processed))
    boundary.bind(encode, lambda identifier: received.pop(0) if received else b"")
    if bridge == "pcm":
        boundary.mute(False)
    decoded = boundary.exchange("a" * 32, b"", 5760)
    scheduled.extend(decoded[offset:offset + 1920] for offset in range(0, len(decoded), 1920))
    assert boundary.exchange("a" * 32, b"\x07\x00" * 960, 0) == b""
    assert pushes == [("a" * 32, b"\x07\x00" * 960, True)]
    assert not received
