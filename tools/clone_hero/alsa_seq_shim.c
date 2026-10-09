/*
 * alsa_seq_shim.c — LD_PRELOAD shim that makes RtMidi's ALSA-sequencer backend
 * succeed without a real /dev/snd/seq.
 *
 * WHY THIS EXISTS
 * --------------
 * Clone Hero (Linux build) initializes its MIDI input through libRtMidi's ALSA
 * backend. RtMidi calls snd_seq_open() and, if that returns 0, assumes a valid
 * snd_seq_t* handle and immediately dereferences it (e.g. MidiInAlsa reads
 * `api->seq` / pollfds). In the AutoRB devcontainer (and any unprivileged
 * container) /dev/snd/seq either does not exist or is blocked by the device
 * cgroup — opening it returns EPERM/ENOENT. libasound then leaves the handle
 * NULL, RtMidi dereferences it, and Unity segfaults on startup
 * ("NullReferenceException" / addr near 0xb0) instead of just disabling MIDI.
 *
 * This shim intercepts the full ALSA-sequencer API that RtMidi touches (51
 * symbols) and returns benign success values, so RtMidi believes a fake MIDI
 * port exists. MIDI input then simply delivers no events — which is exactly
 * right for the AutoRB use case: Clone Hero plays with its built-in bot
 * (--player Guitar,Expert), driven by the chart, not by a real instrument.
 *
 * HOW IT IS USED
 * --------------
 * Built for x86_64 (Clone Hero is x86_64-only; the devcontainer is often
 * arm64, running CH under box64):
 *
 *     x86_64-linux-gnu-gcc -shared -fPIC -O2 \
 *         -o /opt/clonehero/alsa_seq_shim.so alsa_seq_shim.c
 *
 * and preloaded via Box64 (NOT LD_PRELOAD — Box64 filters its own var):
 *
 *     BOX64_LD_PRELOAD=/opt/clonehero/alsa_seq_shim.so
 *
 * Build/idempotence is handled by tools/setup_clone_hero_headless.sh.
 */
#include <stddef.h>
#include <stdlib.h>
#include <poll.h>

/* snd_seq_t is opaque; RtMidi never dereferences it (all access goes through
 * the API we intercept). Any non-NULL pointer is fine. */
static char fake_seq_handle[64];

#define FAKE_OK 0

/* Opened with SND_SEQ_OPEN_INPUT/OUTPUT — we fake success and hand back the
 * fake handle. Returns 0 on success, -errno otherwise (never fails). */
int snd_seq_open(void **handle, const char *name, int streams, int mode) {
    (void)name; (void)streams; (void)mode;
    if (handle) *handle = fake_seq_handle;
    return FAKE_OK;
}

int snd_seq_open_lconf(void **handle, const char *name, int streams, int mode, void *conf) {
    (void)name; (void)streams; (void)mode; (void)conf;
    if (handle) *handle = fake_seq_handle;
    return FAKE_OK;
}

int snd_seq_close(void *handle) {
    (void)handle;
    return FAKE_OK;
}

int snd_seq_nonblock(void *handle, int nonblock) {
    (void)handle; (void)nonblock;
    return FAKE_OK;
}

int snd_seq_set_client_name(void *handle, const char *name) {
    (void)handle; (void)name;
    return FAKE_OK;
}

int snd_seq_client_id(void *handle) {
    (void)handle;
    /* Any positive id makes callers treat the client as valid. */
    return 128;
}

int snd_seq_set_client_info(void *handle, void *info) {
    (void)handle; (void)info;
    return FAKE_OK;
}

int snd_seq_get_client_info(void *handle, void *info) {
    (void)handle; (void)info;
    return FAKE_OK;
}

int snd_seq_get_any_client_info(void *handle, int client, void *info) {
    (void)handle; (void)client; (void)info;
    return FAKE_OK;
}

int snd_seq_get_system_info(void *handle, void *info) {
    (void)handle; (void)info;
    return FAKE_OK;
}

int snd_seq_set_client_pool_input(void *handle, size_t size) {
    (void)handle; (void)size;
    return FAKE_OK;
}

int snd_seq_set_client_pool_output(void *handle, size_t size) {
    (void)handle; (void)size;
    return FAKE_OK;
}

/* --- ports --- */

int snd_seq_create_simple_port(void *handle, const char *name, unsigned int caps, unsigned int type) {
    (void)handle; (void)name; (void)caps; (void)type;
    return 0;
}

int snd_seq_alloc_port(void *handle, unsigned int caps, unsigned int type) {
    (void)handle; (void)caps; (void)type;
    return 0;
}

int snd_seq_alloc_named_port(void *handle, const char *name, unsigned int caps, unsigned int type) {
    (void)handle; (void)name; (void)caps; (void)type;
    return 0;
}

int snd_seq_create_port(void *handle, void *info) {
    (void)handle; (void)info;
    return 0;
}

int snd_seq_delete_port(void *handle, int port) {
    (void)handle; (void)port;
    return FAKE_OK;
}

int snd_seq_set_port_name(void *handle, int port, const char *name) {
    (void)handle; (void)port; (void)name;
    return FAKE_OK;
}

int snd_seq_set_port_info(void *handle, int port, void *info) {
    (void)handle; (void)port; (void)info;
    return FAKE_OK;
}

int snd_seq_get_port_info(void *handle, int port, void *info) {
    (void)handle; (void)port; (void)info;
    return FAKE_OK;
}

/* --- queues --- */

int snd_seq_alloc_named_queue(void *handle, const char *name) {
    (void)handle; (void)name;
    return 0;
}

int snd_seq_alloc_queue(void *handle) {
    (void)handle;
    return 0;
}

int snd_seq_create_queue(void *handle) {
    (void)handle;
    return 0;
}

int snd_seq_delete_queue(void *handle, int q) {
    (void)handle; (void)q;
    return FAKE_OK;
}

int snd_seq_free_queue(void *handle, int q) {
    (void)handle; (void)q;
    return FAKE_OK;
}

int snd_seq_get_queue_tempo(void *handle, int q, void *tempo) {
    (void)handle; (void)q; (void)tempo;
    return FAKE_OK;
}

int snd_seq_set_queue_tempo(void *handle, int q, void *tempo) {
    (void)handle; (void)q; (void)tempo;
    return FAKE_OK;
}

int snd_seq_start_queue(void *handle, int q, void *ev) {
    (void)handle; (void)q; (void)ev;
    return FAKE_OK;
}

int snd_seq_stop_queue(void *handle, int q, void *ev) {
    (void)handle; (void)q; (void)ev;
    return FAKE_OK;
}

/* --- subscriptions --- */

int snd_seq_port_subscribe_malloc(void **ptr) {
    /* RtMidi writes into this struct through the inline accessors in the ALSA
     * headers (set_sender/set_dest/set_queue/...), so it must be real memory.
     * The ALSA struct is ~96 bytes; 256 keeps us clear of heap corruption. */
    void *mem = calloc(1, 256);
    if (!mem) return -12; /* -ENOMEM */
    *ptr = mem;
    return FAKE_OK;
}

int snd_seq_port_subscribe(void *handle, void *subs) {
    (void)handle; (void)subs;
    return FAKE_OK;
}

void snd_seq_port_subscribe_free(void *subs) {
    free(subs);
}

int snd_seq_get_port_subscription(void *handle, void *subs) {
    (void)handle; (void)subs;
    return FAKE_OK;
}

int snd_seq_connect_from(void *handle, int from_port, int src_client, int src_port) {
    (void)handle; (void)from_port; (void)src_client; (void)src_port;
    return FAKE_OK;
}

int snd_seq_connect_to(void *handle, int dest_port, int dst_client, int dst_port) {
    (void)handle; (void)dest_port; (void)dst_client; (void)dst_port;
    return FAKE_OK;
}

int snd_seq_disconnect_from(void *handle, int from_port, int src_client, int src_port) {
    (void)handle; (void)from_port; (void)src_client; (void)src_port;
    return FAKE_OK;
}

int snd_seq_disconnect_to(void *handle, int dest_port, int dst_client, int dst_port) {
    (void)handle; (void)dest_port; (void)dst_client; (void)dst_port;
    return FAKE_OK;
}

int snd_seq_subscribe_port(void *handle, void *sender, void *dest, void *prev) {
    (void)handle; (void)sender; (void)dest; (void)prev;
    return FAKE_OK;
}

int snd_seq_unsubscribe_port(void *handle, void *sender, void *dest, void *prev) {
    (void)handle; (void)sender; (void)dest; (void)prev;
    return FAKE_OK;
}

/* --- events / I/O --- */

/* No events ever: snd_seq_event_input_pending() -> 0 makes RtMidi sleep, and
 * snd_seq_event_input() -> 0 makes its read loop break cleanly. */
int snd_seq_event_input_pending(void *handle, int fetch) {
    (void)handle; (void)fetch;
    return 0;
}

int snd_seq_event_input(void *handle, void **ev) {
    (void)handle; (void)ev;
    return 0;
}

int snd_seq_event_output(void *handle, void *ev) {
    (void)handle; (void)ev;
    return 0;
}

int snd_seq_drain_output(void *handle) {
    (void)handle;
    return FAKE_OK;
}

int snd_seq_drop_output(void *handle) {
    (void)handle;
    return FAKE_OK;
}

int snd_seq_drop_input(void *handle) {
    (void)handle;
    return FAKE_OK;
}

int snd_seq_sync_output_queue(void *handle) {
    (void)handle;
    return FAKE_OK;
}

int snd_seq_remove_events(void *handle, void *cond) {
    (void)handle; (void)cond;
    return FAKE_OK;
}

void snd_seq_free_event(void *ev) {
    (void)ev;
}

/* --- polling --- */

/* Return 0 descriptors so RtMidi's poll() gets an empty set and merely sleeps
 * (the MIDI thread never blocks on a real fd and never crashes). */
int snd_seq_poll_descriptors_count(void *handle, struct pollfd *pfds, unsigned int space) {
    (void)handle; (void)pfds; (void)space;
    return 0;
}

int snd_seq_poll_descriptors(void *handle, struct pollfd *pfds, unsigned int space, int timeout) {
    (void)handle; (void)pfds; (void)space; (void)timeout;
    return 0;
}

/* --- enumeration (terminate immediately) --- */

int snd_seq_query_next_client(void *handle, void *info) {
    (void)handle; (void)info;
    return -1;
}

int snd_seq_query_next_port(void *handle, void *info) {
    (void)handle; (void)info;
    return -1;
}
