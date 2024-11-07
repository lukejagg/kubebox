#!/bin/bash

docker buildx build --platform linux/amd64 -t lukejagg/sandbox:latest .
