FROM h2load:local
FROM nginx-build:local

RUN apt-get update && \
  apt-get install -y wget net-tools iputils-ping tcpdump ethtool iperf iproute2

COPY --from=h2load:local /usr/local/bin/h2load /usr/local/bin/h2load
COPY --from=nginx-build:local /usr/local/nginx/sbin/nginx /usr/local/nginx/sbin/nginx

COPY setup.sh .
RUN chmod +x setup.sh

COPY run_endpoint.sh .
RUN chmod +x run_endpoint.sh

RUN wget --ca-certificate=/etc/ssl/certs/ca-certificates.crt \
      https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh \
 && chmod +x wait-for-it.sh

ENTRYPOINT [ "/run_endpoint.sh" ]
