FROM ubuntu:24.04

RUN apt-get update && \
  apt-get install -y wget net-tools iputils-ping tcpdump ethtool iperf iproute2

# h2load (nghttp2) HTTP/3 client, built from pinned sources, plus the runtime
# libraries the mounted patched nginx needs. One image serves both roles.
ARG OPENSSL_VERSION=3.5.0
ARG NGHTTP3_VERSION=v1.12.0
ARG NGTCP2_VERSION=v1.16.0
ARG NGHTTP2_VERSION=v1.69.0

RUN apt-get install -y --no-install-recommends \
      git g++ make binutils autoconf automake autotools-dev libtool pkg-config \
      cmake zlib1g-dev libev-dev libc-ares-dev libevent-dev ca-certificates curl \
      libpcre3 libpcre2-8-0 zlib1g \
    && rm -rf /var/lib/apt/lists/*

ENV PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:/usr/local/lib64/pkgconfig
ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/local/lib64

WORKDIR /src
RUN curl -fsSL "https://github.com/openssl/openssl/releases/download/openssl-${OPENSSL_VERSION}/openssl-${OPENSSL_VERSION}.tar.gz" | tar xz \
 && cd "openssl-${OPENSSL_VERSION}" \
 && ./Configure --prefix=/usr/local --libdir=lib enable-tls1_3 \
 && make -j"$(nproc)" && make install_sw && ldconfig
RUN git clone --depth 1 -b "${NGHTTP3_VERSION}" https://github.com/ngtcp2/nghttp3 \
 && cd nghttp3 && git submodule update --init --depth 1 \
 && autoreconf -i && ./configure --prefix=/usr/local --enable-lib-only \
 && make -j"$(nproc)" && make install && ldconfig
RUN git clone --depth 1 -b "${NGTCP2_VERSION}" https://github.com/ngtcp2/ngtcp2 \
 && cd ngtcp2 && git submodule update --init --depth 1 \
 && autoreconf -i && ./configure --prefix=/usr/local --enable-lib-only --with-openssl \
 && make -j"$(nproc)" && make install && ldconfig
RUN git clone --depth 1 -b "${NGHTTP2_VERSION}" https://github.com/nghttp2/nghttp2 \
 && cd nghttp2 && git submodule update --init --depth 1 \
 && autoreconf -i \
 && ./configure --prefix=/usr/local --enable-app --enable-http3 --without-jemalloc \
      --with-libnghttp3 --with-libngtcp2 --with-openssl \
 && make -j"$(nproc)" && make install && ldconfig
RUN h2load --version > /usr/local/share/h2load-build.txt \
 && printf '%s\n' "OpenSSL=${OPENSSL_VERSION}" "nghttp3=${NGHTTP3_VERSION}" \
      "ngtcp2=${NGTCP2_VERSION}" "nghttp2=${NGHTTP2_VERSION}" \
      >> /usr/local/share/h2load-build.txt

WORKDIR /
COPY setup.sh .
RUN chmod +x setup.sh

COPY run_endpoint.sh .
RUN chmod +x run_endpoint.sh

RUN wget --ca-certificate=/etc/ssl/certs/ca-certificates.crt \
      https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh \
 && chmod +x wait-for-it.sh

ENTRYPOINT [ "/run_endpoint.sh" ]
