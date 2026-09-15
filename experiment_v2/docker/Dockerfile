# Authoritative experiment image for the lab PC (build and run on the PC, linux/amd64).
# Both Defects4J releases are installed side by side; the version used by the experiment is chosen by the
# checkout/compile/trigger-test verification stage and frozen in protocol/protocol.yaml.
FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG D4J_V2_COMMIT=a83e47921152721569cb95d6d7b91c4be277d940   # tag v2.0.1
ARG D4J_V3_COMMIT=6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09   # tag v3.0.1
ARG SPOTBUGS_VERSION=4.9.3
ARG FINDSECBUGS_VERSION=1.14.0

RUN apt-get update && apt-get install -y --no-install-recommends \
      openjdk-8-jdk openjdk-11-jdk openjdk-21-jdk maven \
      git subversion perl cpanminus build-essential libdbi-perl \
      curl unzip ca-certificates python3 python3-venv python3-pip locales \
    && rm -rf /var/lib/apt/lists/* \
    && locale-gen en_US.UTF-8

ENV LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 TZ=America/Los_Angeles
ENV JDK8=/usr/lib/jvm/java-8-openjdk-amd64 JDK11=/usr/lib/jvm/java-11-openjdk-amd64 JDK21=/usr/lib/jvm/java-21-openjdk-amd64

# Defects4J v2.0.1 (JDK 8)
RUN git clone https://github.com/rjust/defects4j /opt/defects4j-2.0.1 \
    && cd /opt/defects4j-2.0.1 && git checkout ${D4J_V2_COMMIT} \
    && cpanm --notest --installdeps . \
    && JAVA_HOME=$JDK8 PATH=$JDK8/bin:$PATH ./init.sh

# Defects4J v3.0.1 (JDK 11)
RUN git clone https://github.com/rjust/defects4j /opt/defects4j-3.0.1 \
    && cd /opt/defects4j-3.0.1 && git checkout ${D4J_V3_COMMIT} \
    && cpanm --notest --installdeps . \
    && JAVA_HOME=$JDK11 PATH=$JDK11/bin:$PATH ./init.sh

# SpotBugs + FindSecBugs (run on JDK 21)
RUN curl -fsSL -o /tmp/spotbugs.tgz \
      https://github.com/spotbugs/spotbugs/releases/download/${SPOTBUGS_VERSION}/spotbugs-${SPOTBUGS_VERSION}.tgz \
    && tar -xzf /tmp/spotbugs.tgz -C /opt && ln -s /opt/spotbugs-${SPOTBUGS_VERSION} /opt/spotbugs \
    && curl -fsSL -o /opt/spotbugs/plugin/findsecbugs-plugin-${FINDSECBUGS_VERSION}.jar \
      https://repo1.maven.org/maven2/com/h3xstream/findsecbugs/findsecbugs-plugin/${FINDSECBUGS_VERSION}/findsecbugs-plugin-${FINDSECBUGS_VERSION}.jar \
    && rm /tmp/spotbugs.tgz

# Python environment
COPY requirements.txt /opt/qc/requirements.txt
RUN python3 -m venv /opt/qc/venv \
    && /opt/qc/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/qc/venv/bin/pip install --no-cache-dir -r /opt/qc/requirements.txt

RUN git config --global --add safe.directory /work

ENV PATH=/opt/qc/venv/bin:/opt/spotbugs/bin:$PATH
WORKDIR /work
# Mount the repository at /work and workspaces at /data/qc_workspaces:
#   docker run --rm -it -v "$PWD":/work -v /data/qc_workspaces:/data/qc_workspaces qc-v2 bash
