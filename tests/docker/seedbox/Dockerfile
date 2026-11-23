FROM python:3.12-alpine
ARG SEED_UID=1000
RUN apk add --no-cache openssh && mkdir /run/sshd \
    && adduser -D -u "$SEED_UID" seed && echo 'seed:disposable-test-password' | chpasswd
COPY sshd_config /etc/ssh/sshd_config
CMD ["sh", "-c", "ssh-keygen -A && exec /usr/sbin/sshd -D -e"]
