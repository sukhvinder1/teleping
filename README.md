# ntfy on Google Cloud Run

This repo deploys [ntfy](https://ntfy.sh) (self-hosted push notification
server) to Google Cloud Run using the official `binwiederhier/ntfy` image.

## Files

- `Dockerfile` — wraps the official ntfy image, binds it to Cloud Run's
  `$PORT`.
- `server/ntfy.yml` — ntfy server config, tuned for Cloud Run's ephemeral
  filesystem (in-memory cache).
- `deploy-cloudrun.sh` — builds the image with Cloud Build and deploys it to
  Cloud Run.

## Deploy

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

PROJECT_ID=YOUR_PROJECT_ID REGION=us-central1 SERVICE_NAME=ntfy \
  bash deploy-cloudrun.sh
```

After the first deploy, update `base-url` in `server/ntfy.yml` to the
Cloud Run URL you're given, then redeploy so ntfy generates correct links
in notifications.

## Important limitations on Cloud Run

- **No persistent disk.** Cloud Run containers are stateless and can be
  killed/rescheduled at any time. This config uses `cache-file: ":memory:"`,
  so message history, attachments, and any local auth database are lost on
  every restart or scale-to-zero event. If you need durable message
  history, user accounts, or attachments, either:
  - mount a [Cloud Storage FUSE volume](https://cloud.google.com/run/docs/configuring/services/cloud-storage-volume-mounts) for the cache/attachment dirs, or
  - run ntfy on a small GCE VM or GKE with a real persistent disk instead.
- **Long-lived connections.** ntfy clients hold open WebSocket/SSE
  connections for real-time delivery. The deploy script sets
  `--min-instances 1` (avoid cold starts dropping connections),
  `--timeout 3600` (max request duration), and `--session-affinity`.
- **Concurrency**: adjust `--concurrency` based on expected number of
  simultaneous subscribers per instance.
- **Auth**: for a private instance, set `auth-default-access: deny-all` and
  configure users via `ntfy user add`, but remember the auth database also
  needs persistent storage to survive restarts (see above).

## Alternative: GCE VM

If you need durable storage without extra plumbing, a small `e2-micro` GCE
VM running ntfy via `apt` or Docker with a persistent disk is simpler and
avoids the stateless-storage caveats above.
