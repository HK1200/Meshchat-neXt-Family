# The pinned opusfile release has no CMake project. Compile its four core
# files only: no URL/HTTP helper, TLS library or network access is included.
cmake_minimum_required(VERSION 3.16)
project(FamilyOpusFile LANGUAGES C)
foreach(required OPUSFILE_SOURCE OPUS_SOURCE OGG_SOURCE OGG_BUILD)
  if(NOT DEFINED ${required})
    message(FATAL_ERROR "${required} must identify verified codec sources")
  endif()
endforeach()
add_library(opusfile STATIC
  "${OPUSFILE_SOURCE}/src/info.c"
  "${OPUSFILE_SOURCE}/src/internal.c"
  "${OPUSFILE_SOURCE}/src/opusfile.c"
  "${OPUSFILE_SOURCE}/src/stream.c")
target_include_directories(opusfile PRIVATE "${OPUSFILE_SOURCE}/include"
  "${OPUS_SOURCE}/include" "${OGG_SOURCE}/include" "${OGG_BUILD}/include")
target_compile_definitions(opusfile PRIVATE OP_HAVE_LRINTF=1)
