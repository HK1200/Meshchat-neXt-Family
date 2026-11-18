/* SPDX-License-Identifier: 0BSD */
/* Derived from Meshchat neXt's Baresip engine, with native iOS callbacks. */
#include "FamilySIP.h"
#include <pthread.h>
#include <re.h>
#include <baresip.h>
#define DEBUG_MODULE "family_sip"
#define DEBUG_LEVEL 0
#include <re_dbg.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
static struct mqueue *queue;
static struct ua *agent;
static struct call *current;
static struct tmr digit_timer;
static struct tmr shutdown_timer;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static FamilySIPEvent listener;
static bool running;
static char current_call_id[80];
static unsigned long long call_sequence;
struct control { char *value; char *call_id; };
static void control_destructor(void *arg) {
    struct control *control = arg;
    mem_deref(control->value);
    mem_deref(control->call_id);
}
static void native_call_id(void) {
    snprintf(current_call_id, sizeof(current_call_id), "native-%llu", ++call_sequence);
}
static void event_for_call(const char *state, const char *peer, int code, const char *call_id) {
    if (listener) listener(state, peer ? peer : "", code, call_id ? call_id : "");
}
static void event(const char *state, const char *peer, int code) {
    event_for_call(state, peer, code, current_call_id);
}
static void finish_shutdown(void *arg) { (void)arg; re_cancel(); }
static void release_digit(void *arg) { (void)arg; if(current) call_send_digit(current,KEYCODE_REL); }
static void events(enum bevent_ev ev, struct bevent *e, void *arg) {
    (void)arg;
    struct call *c = bevent_get_call(e);
    switch (ev) {
        case BEVENT_REGISTERING:
            event("registering", NULL, 0);
            break;
        case BEVENT_REGISTER_OK:
            event("registered", NULL, 0);
            break;
        case BEVENT_REGISTER_FAIL: {
            const char *text = bevent_get_text(e);
            int code = 0;
            if (text && text[0] >= '0' && text[0] <= '9')
                code = atoi(text);
            else if (text) {
                for (int n = 1; n < 200; n++)
                    if (!strcmp(text, strerror(n))) {
                        code = -n;
                        break;
                    }
            }
            event("registration_failed", NULL, code);
            break;
        }
        case BEVENT_CALL_INCOMING:
            if (current && current != c) {
                call_hangup(c, 486, "Busy");
                break;
            }
            current = c;
            native_call_id();
            event("incoming", call_peeruri(c), 0);
            break;
        case BEVENT_CALL_OUTGOING:
            current = c;
            if (!current_call_id[0]) native_call_id();
            event("calling", call_peeruri(c), 0);
            break;
        case BEVENT_CALL_RINGING:
            if (c != current) break;
            event("ringing", call_peeruri(c), 0);
            break;
        case BEVENT_CALL_PROGRESS:
            if (c != current) break;
            event("progress", call_peeruri(c), 0);
            break;
        case BEVENT_CALL_ESTABLISHED:
            if (c != current) break;
            event("connected", call_peeruri(c), 0);
            break;
        case BEVENT_CALL_RTCP:
            break;
        case BEVENT_CALL_CLOSED:
            tmr_cancel(&digit_timer);
            if (current == c) {
                char ended_id[sizeof(current_call_id)];
                memcpy(ended_id, current_call_id, sizeof(ended_id));
                current = NULL;
                current_call_id[0] = '\0';
                event_for_call("ended", call_peeruri(c), 0, ended_id);
            }
            break;
        case BEVENT_AUDIO_ERROR:
            if (c != current) break;
            event("audio_error", NULL, 0);
            break;
        default:
            break;
    }
}
static void commands(int id, void *data, void *arg) {
    (void)arg;
    int err = 0;
    struct control *control = data;
    char *text = control->value;
    if (id != 1 && id != 9 && !family_sip_call_matches(control->call_id, current_call_id)) {
        mem_deref(data);
        return;
    }
    switch (id) {
        case 1:
            if (!current && agent) {
                if (control->call_id) snprintf(current_call_id, sizeof(current_call_id), "%s", control->call_id);
                else native_call_id();
                err = ua_connect(agent, &current, NULL, text, VIDMODE_OFF);
            } else err = EBUSY;
            break;
        case 2:
            if (current) err = ua_answer(agent, current, VIDMODE_OFF);
            break;
        case 3:
            if (current) ua_hangup(agent, current, 0, NULL);
            break;
        case 4:
            if (current) {
                audio_mute(call_audio(current), text && text[0] == '1');
                event("muted", NULL, audio_ismuted(call_audio(current)) ? 1 : 0);
            }
            break;
        case 5:
            if (current && text && text[0]) {err = call_send_digit(current, text[0]);tmr_start(&digit_timer,150,release_digit,NULL);}
            break;
        case 6:
            if (current) err = call_hold(current, text && text[0] == '1');
            break;
        case 7:
            if (current) {
                audio_stop(call_audio(current));
                err = audio_update(call_audio(current));
                if (err) {
                    event("audio_error", NULL, err);
                    err = 0;
                }
            }
            break;
        case 8:
            if (current) audio_stop(call_audio(current));
            break;
        case 9:
            /* Allow the authenticated expires=0 transaction to finish before
               stopping the event loop. Never wait indefinitely for a dead network. */
            if (agent) {
                if (current) ua_hangup(agent, current, 0, NULL);
                ua_unregister(agent);
            }
            tmr_start(&shutdown_timer, 1500, finish_shutdown, NULL);
            break;
    }
    if (err) {
        event_for_call("command_failed", NULL, err, control->call_id ? control->call_id : current_call_id);
        if (id == 1 && !current) current_call_id[0] = '\0';
    }
    mem_deref(data);
}

static int enqueue(int operation, const char *value, const char *call_id) {
    struct control *control = mem_zalloc(sizeof(*control), control_destructor);
    if (!control) return ENOMEM;
    int err = value ? str_dup(&control->value, value) : 0;
    if (!err && call_id) err = str_dup(&control->call_id, call_id);
    if (err) { mem_deref(control); return err; }
    pthread_mutex_lock(&lock);
    err = queue ? mqueue_push(queue, operation, control) : ENOENT;
    pthread_mutex_unlock(&lock);
    if (err) mem_deref(control);
    return err;
}
void family_sip_command(int operation, const char *value) { (void)enqueue(operation, value, NULL); }
int family_sip_call_command(int operation, const char *value, const char *call_id) {
    if (!call_id || !call_id[0] || strlen(call_id) >= sizeof(current_call_id)) return EINVAL;
    return enqueue(operation, value, call_id);
}

int family_sip_run(const char *user, const char *host, int port,
                   const char *password, FamilySIPEvent callback) {
    if (!user || !host || !password || !callback || port < 1 || port > 65535) return EINVAL;
    pthread_mutex_lock(&lock);
    if (running) { pthread_mutex_unlock(&lock); return EBUSY; }
    running = true;
    listener = callback;
    pthread_mutex_unlock(&lock);
    int err = 0;
    char aor[768];
#ifdef FAMILY_SIP_TEST_DIAGNOSTICS
    /* Only the private simulator fixture compiles this diagnostic path. */
    log_enable_stdout(true);
    log_enable_debug(false);
    log_enable_info(true);
    dbg_init(DBG_INFO, 0);
#else
    log_enable_stdout(false);
    log_enable_debug(false);
    log_enable_info(false);
    dbg_init(DBG_EMERG, 0);
#endif
    err = libre_init();
    if (err) goto finish;
    re_thread_async_init(2);
    const char *config =
        "audio_player audiounit,default\naudio_source audiounit,default\n"
        "audio_alert audiounit,default\naudio_buffer 20-160\n"
        "audio_jitter_buffer_type adaptive\naudio_jitter_buffer_ms 40-200\n"
        "call_max_calls 1\ncall_accept yes\nnet_af ipv4\nsip_cuser_random no\n"
        "sip_listen 0.0.0.0:0\n";
    err = conf_configure_buf((const uint8_t *)config, strlen(config));
    if (err) goto close;
    err = baresip_init(conf_config());
    if (err) goto close;
    err = ua_init("neXt Family iOS", true, false, false);
    if (err) goto close;
    const char *modules[] = {"audiounit", "g711", "opus", NULL};
    for (int i = 0; modules[i]; i++) {
        err = module_preload(modules[i]);
        if (err) goto close;
    }
    err = bevent_register(events, NULL);
    if (err) goto close;
    re_snprintf(aor, sizeof(aor),
        "<sip:%s@%s:%d;transport=udp>;regint=0;audio_codecs=opus/48000/2,PCMU/8000/1,PCMA/8000/1;ptime=20;rtpkeep=zero",
        user, host, port);
    err = ua_alloc(&agent, aor);
    if (err) goto close;
    err = account_set_auth_user(ua_account(agent), user);
    if (err) goto close;
    err = account_set_auth_pass(ua_account(agent), password);
    if (err) goto close;
    account_set_regint(ua_account(agent), 3600);
    pthread_mutex_lock(&lock);
    err = mqueue_alloc(&queue, commands, NULL);
    pthread_mutex_unlock(&lock);
    if (err) goto close;
    err = ua_register(agent);
    if (err) goto close;
    event("ready", NULL, 0);
    err = re_main(NULL);
close:
    pthread_mutex_lock(&lock);
    queue = mem_deref(queue);
    pthread_mutex_unlock(&lock);
    tmr_cancel(&digit_timer);
    tmr_cancel(&shutdown_timer);
    current = NULL;
    current_call_id[0] = '\0';
    agent = NULL;
    bevent_unregister(events);
    ua_stop_all(true);
    ua_close();
    baresip_close();
    conf_close();
    mod_close();
    re_thread_async_close();
    libre_close();
finish:
    if (err) event("engine_failed", NULL, err);
    FamilySIPEvent finished = listener;
    pthread_mutex_lock(&lock);
    listener = NULL;
    running = false;
    pthread_mutex_unlock(&lock);
    /* The callback may immediately start the replacement account. */
    if (finished) finished("stopped", "", err, "");
    return err;
}
