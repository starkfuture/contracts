# Stark DocuSeal: the official image, unchanged, plus build/app (patched upstream files + overlay/).
# Build with: python3 tools/assemble.py && docker build .
# The base digest must match UPSTREAM (CI checks it).
FROM 952414816681.dkr.ecr.eu-west-1.amazonaws.com/docuseal:3.3.6@sha256:df78e750ec0df42c121225875714487998048c9c80f412c1d5a0b9290887ba5c

COPY --chown=docuseal:docuseal build/app/ /app/
COPY --chown=docuseal:docuseal UPSTREAM FORK.md /app/stark/

RUN cd /app && bundle exec bootsnap precompile -j 1 app/ lib/ && chown -R docuseal:docuseal /app/tmp/cache
