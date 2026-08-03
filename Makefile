aoi ?= fire_lake
IMAGE := moose-scout:local
MOUNTS := -v $(PWD)/config:/app/config:ro -v $(PWD)/cache:/app/cache -v $(PWD)/outputs:/app/outputs
RUN := docker run --rm $(MOUNTS) $(IMAGE)

.PHONY: build legal acquire terrain habitat access synth export run shell test clean

build:
	docker build -f docker/Dockerfile -t $(IMAGE) .

legal:   ; $(RUN) legal --aoi $(aoi)
acquire: ; $(RUN) acquire --aoi $(aoi)
terrain: ; $(RUN) terrain --aoi $(aoi)
habitat: ; $(RUN) habitat --aoi $(aoi)
access:  ; $(RUN) access --aoi $(aoi)
synth:   ; $(RUN) synth --aoi $(aoi)
export:  ; $(RUN) export --aoi $(aoi)
run:     ; $(RUN) run --aoi $(aoi)

shell:
	docker run --rm -it $(MOUNTS) --entrypoint bash $(IMAGE)

test:
	docker run --rm $(MOUNTS) --entrypoint pytest $(IMAGE) -q

clean:
	rm -rf cache/$(aoi) outputs/$(aoi)
