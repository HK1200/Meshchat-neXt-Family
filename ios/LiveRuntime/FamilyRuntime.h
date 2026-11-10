#ifndef FAMILY_RUNTIME_H
#define FAMILY_RUNTIME_H

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Start once before serving requests. NULL python_home uses the default stdlib. */
bool family_runtime_start(const char *python_home, const char *modules, const char *state);

/* Returns owned UTF-8 JSON, or NULL on a bridge failure. Free with free(). */
char *family_runtime_request(const char *json);

#ifdef __cplusplus
}
#endif

#endif
