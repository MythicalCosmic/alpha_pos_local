# Reproducible Windows (x86_64-pc-windows-msvc) build image for the Tauri shell.
# Frontend assets are built on the host; this image only compiles Rust and
# packages the NSIS installer.
FROM rust:1-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends nsis clang lld llvm ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN rustup target add x86_64-pc-windows-msvc \
 && cargo install --locked cargo-xwin \
 && cargo install --locked tauri-cli --version "^2"

# The MSVC CRT/SDK is downloaded by cargo-xwin into this cache; mount it as a
# volume so it is fetched once.
ENV XWIN_ACCEPT_LICENSE=1 \
    XWIN_CACHE_DIR=/xwin-cache \
    CARGO_HOME=/usr/local/cargo

WORKDIR /work
