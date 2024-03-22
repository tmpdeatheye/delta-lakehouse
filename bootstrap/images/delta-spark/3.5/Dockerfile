FROM maven:3.9.6-eclipse-temurin-17 AS builder

WORKDIR /tmp

COPY ./pom.xml ./

RUN mvn -f pom.xml dependency:resolve dependency:copy-dependencies -DoutputDirectory=/tmp/delta-spark

FROM library/spark:3.5.1-java17-python3

COPY --from=builder /tmp/delta-spark/ /opt/spark/jars/
