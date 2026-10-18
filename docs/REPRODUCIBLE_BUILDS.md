# Reproducible OCI image verification

## What CI proves

The VyralX CI job first builds the normal scan target, then builds the same checked-out commit twice using separate ephemeral BuildKit builders. Both extra builds use:

- The immutable Python base-image digest and dated Debian package snapshot defined in the Dockerfile.
- A frozen uv.lock plus hash-checked PEP 517 build dependencies.
- --no-cache and --pull so neither build silently reuses a prior result.
- SOURCE_DATE_EPOCH set to the checked-out commit timestamp; the OCI exporter uses forced gzip compression at level 9 and rewrites layer timestamps.
- A local OCI layout tarball; the build does not push to a registry or deploy an image.

scripts/compare_oci_images.py validates the OCI index and referenced descriptors, checks every SHA-256 blob against its content-addressed filename, verifies manifest descriptor sizes, and compares all OCI layout member names and exact payload bytes. It deliberately ignores outer tar member ordering and tar-header timestamps, which are packaging metadata rather than image contents. Archive hashes are printed for traceability, but the pass/fail decision is based on exact identity of the OCI layout payloads. Different/missing/extra files, changed layers/configuration, invalid descriptors, corrupt blobs, and unsafe archive members all fail validation.

When a comparison fails, the helper prints each manifest layer blob digest alongside the image config uncompressed rootfs diff_id. Matching diff_ids with different blob digests suggest a compression/serialization difference; different diff_ids identify differing filesystem-layer content. Keep this output with the failed run and investigate the responsible layer instead of bypassing the gate.

The resulting CI record is evidence for the tested commit and Linux/amd64 build path only. It does not prove that a future commit, ARM64 output, a different BuildKit/toolchain version, or an Oracle/Dokploy deployment is reproducible. Retain the exact run link with release evidence; repeat the check on the final release candidate and rerun security scanning on that same commit.

## Manual artifact comparison

With Docker Buildx and a BuildKit version that supports OCI timestamp rewriting installed, build two clean OCI artifacts from the same checkout using separate builders. Use the commit timestamp as SOURCE_DATE_EPOCH, --no-cache, --pull, and --output type=oci,dest=.../rewrite-timestamp=true for each build. Then run this command from the repository root:

    python scripts/compare_oci_images.py first.oci.tar second.oci.tar

Exit code 0 means the full OCI layout payloads match byte-for-byte. Exit code 1 means the two valid builds differ; exit code 2 means an archive could not be validated. The outer archive hashes are displayed, but differences only in tar packaging metadata do not make otherwise identical OCI image payloads fail. Preserve the output and CI URL in the release record.

A successful comparison is only one release gate. Actual Dokploy networking, secret mounts, worker readiness, persistent volumes, encrypted backup/restore, target-VM resource profiling, FRIDAY mesh authentication, and YouTube OAuth/private-upload acceptance remain separate operator/environment checks.
