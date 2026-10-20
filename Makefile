# Thin wrappers around `docker run`. Usage: make build, make run, make shell, ...
IMAGE   ?= robot:dev
CAMERA  ?= /dev/video0
UID     := $(shell id -u)
GID     := $(shell id -g)
VIDEO_GID := $(shell getent group video | cut -d: -f3)

# Speaker: on a desktop, share the PulseAudio/PipeWire socket; on a bare Pi,
# use `make AUDIO=alsa ...`, which passes the sound card straight through.
AUDIO ?= pulse
ifeq ($(AUDIO),pulse)
AUDIO_ARGS := -v /run/user/$(UID)/pulse/native:/run/pulse/native -e PULSE_SERVER=unix:/run/pulse/native
else
AUDIO_ARGS := --device /dev/snd --group-add $(shell getent group audio | cut -d: -f3)
endif

# Settings come from .env; credentials exported in your shell override it.
# Claude login: the robot's own long-lived token from `make claude-token`, in .env as
# CLAUDE_CODE_OAUTH_TOKEN. (Not ~/.claude: that's this laptop's rotating login, and a
# copy refreshing itself in the container would log Claude Code out here.)
ENV_FILE := $(if $(wildcard .env),--env-file .env,)
PASS_ENV := -e CLAUDE_CODE_OAUTH_TOKEN -e ANTHROPIC_API_KEY
DOCKER_RUN = docker run --rm -it \
	--user $(UID):$(GID) --group-add $(VIDEO_GID) \
	-v $(CURDIR)/data:/data $(ENV_FILE) $(PASS_ENV) $(AUDIO_ARGS)

.PHONY: build run run-nocam analyze react simulate enroll enroll-cam faces say ask listen-test transcribe claude-token test shell

build:
	docker build -t $(IMAGE) .

data:
	mkdir -p data/spool data/snapshots data/audio

## Full robot: Motion + vision + Claude + speech. Live stream at http://localhost:8081
run: data
	$(DOCKER_RUN) --name robot --device $(CAMERA):/dev/video0 -p 8080:8080 -p 8081:8081 $(IMAGE) run

## Brain only, no camera: feed it pictures with `make simulate IMG=...`
run-nocam: data
	$(DOCKER_RUN) --name robot -e ROBOT_MOTION=0 $(IMAGE) run

## make analyze IMG=data/test.jpg   (what the detectors see; no Claude)
analyze: data
	$(DOCKER_RUN) $(IMAGE) analyze /data/$(notdir $(IMG))

## make react IMG=data/test.jpg     (detect + Claude + speech, once)
react: data
	$(DOCKER_RUN) $(IMAGE) react /data/$(notdir $(IMG))

## make simulate IMG=data/test.jpg  (queue a picture for a running robot)
simulate: data
	$(DOCKER_RUN) $(IMAGE) simulate /data/$(notdir $(IMG))

## make enroll NAME=Stjepan IMGS="data/me1.jpg data/me2.jpg"
enroll: data
	$(DOCKER_RUN) $(IMAGE) enroll $(NAME) $(foreach f,$(IMGS),/data/$(notdir $(f)))

## make enroll-cam NAME=Stjepan     (stop `make run` first; it holds the camera)
enroll-cam: data
	$(DOCKER_RUN) --device $(CAMERA):/dev/video0 $(IMAGE) enroll-cam $(NAME)

faces: data
	$(DOCKER_RUN) $(IMAGE) faces

## make say TEXT="hello there" [IN=hr]
say: data
	$(DOCKER_RUN) $(IMAGE) say $(if $(IN),--lang $(IN)) $(TEXT)

## make ask TEXT="what do you see?" [IN=hr]   (talk to it by typing; no microphone)
ask: data
	$(DOCKER_RUN) $(IMAGE) ask $(if $(IN),--lang $(IN)) $(TEXT)

## Wake word + speech-to-text only: prints what it heard, doesn't call Claude
listen-test: data
	$(DOCKER_RUN) $(IMAGE) listen --test

## make transcribe WAV=data/me.wav  (16 kHz mono)
transcribe: data
	$(DOCKER_RUN) $(IMAGE) transcribe /data/$(notdir $(WAV))

## One-time: create a long-lived Claude Code token (opens a browser login), runs on the host.
## Put the printed token in .env as CLAUDE_CODE_OAUTH_TOKEN=...
claude-token:
	claude setup-token

test:
	docker run --rm --entrypoint python $(IMAGE) -m unittest discover -s tests -v

shell: data
	$(DOCKER_RUN) --device $(CAMERA):/dev/video0 --entrypoint bash $(IMAGE)
