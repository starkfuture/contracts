# Stark DocuSeal: the official image, unchanged, plus build/app (patched upstream files + overlay/).
# Only a COPY: nothing runs at build time, so both architectures build the same. Bootsnap compiles
# the copied files on first load.
# BASE is the multi-arch upstream index mirrored in ECR, from UPSTREAM:
#   docker build --build-arg BASE=$(sed -n 's/^MIRROR=//p' UPSTREAM) .
ARG BASE
FROM ${BASE}

COPY --chown=docuseal:docuseal build/app/ /app/
