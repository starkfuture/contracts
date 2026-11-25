# Stark DocuSeal: the official image, unchanged, plus build/app (patched upstream files + overlay/).
# Only a COPY: nothing runs at build time, so both architectures build without emulation. Bootsnap
# compiles the copied files on first load.
# The base is the multi-arch index (amd64 + arm64) mirrored in ECR; it must match UPSTREAM (CI checks).
FROM 952414816681.dkr.ecr.eu-west-1.amazonaws.com/docuseal:3.3.6@sha256:df78e750ec0df42c121225875714487998048c9c80f412c1d5a0b9290887ba5c

COPY --chown=docuseal:docuseal build/app/ /app/
