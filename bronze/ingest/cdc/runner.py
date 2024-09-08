from confluent_kafka.schema_registry import SchemaRegistryClient
from delta import *
from delta.tables import *
from pyspark.sql.avro.functions import *
from pyspark.sql.functions import *

conf = {
    "spark.hadoop.fs.s3a.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
    "spark.hadoop.fs.s3a.endpoint": "http://10.1.1.2:9000",
    "spark.hadoop.fs.s3a.access.key": "username",
    "spark.hadoop.fs.s3a.secret.key": "password",
    "spark.hadoop.fs.s3a.path.style.access": "true",
    "spark.sql.catalogImplementation": "hive",
    "spark.hive.metastore.uris": "thrift://10.1.1.7:9083",
    "spark.hive.metastore.schema.verification": "false",
    "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
    "spark.sql.catalog.spark_catalog": "org.apache.spark.sql.delta.catalog.DeltaCatalog",
    "spark.sql.debug.maxToStringFields": "1024",
    "spark.sql.legacy.timeParserPolicy": "LEGACY"
}

packages = [
    "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1",
    "org.apache.spark:spark-avro_2.12:3.5.1",
    "org.apache.hadoop:hadoop-aws:3.3.4",
    "io.delta:delta-spark_2.12:3.1.0"
]

spark = configure_spark_with_delta_pip(
    spark_session_builder=SparkSession.builder.config(map=conf),
    extra_packages=packages
).getOrCreate()

# kafka definition
kafka_url = "10.1.1.9:9092"
schema_registry_url = "http://10.1.1.10:8081"
subscribed_topic = "debezium.teko.billing.billing.invoice"
schema_registry_subject = f"{subscribed_topic}-value"


def get_schema_from_schema_registry(url: str, subject: str) -> str:
    sr = SchemaRegistryClient({
        "url": url
    })
    return sr.get_latest_version(subject).schema.schema_str


invoice = (
    spark.readStream
    .format("kafka")
    .option("kafka.bootstrap.servers", kafka_url)
    .option("subscribe", subscribed_topic)
    .option("startingOffsets", "earliest")
    .load()
)

latest_schema = get_schema_from_schema_registry(schema_registry_url, schema_registry_subject)
from_avro_options = {
    "mode": "PERMISSIVE"
}

value = (
    invoice
    .withColumn("fixedValue", expr("substring(value, 6, length(value) - 5)"))
    .select(
        from_avro(
            col("fixedValue"),
            latest_schema,
            from_avro_options
        ).alias("fields")
    )
    .select(
        # if op = 'd' then order_id = fields.before.order_id else order_id = fields.after.order_id
        when(col("fields.op") == "d", col("fields.before.order_id")).otherwise(col("fields.after.order_id")).alias("order_id"),
        when(col("fields.op") == "d", col("fields.before.created_at")).otherwise(col("fields.after.created_at")).alias("created_at"),
        when(col("fields.op") == "d", col("fields.before.description")).otherwise(col("fields.after.description")).alias("description"),
        col("fields.op").alias("op")
    )
    .withColumn("date", to_date(col("created_at"), "yyyy-MM-dd"))
)

dt = DeltaTable.forName(spark, "billing.invoice")
checkpoint_location = f"s3a://lakehouse/_checkpoints/vnshop/main/fact/rate/_checkpoint/"


def merge_batch_into(batch: DataFrame, batch_id: int):
    (
        dt.alias("target")
        .merge(
            batch.alias("source").filter(col("order_id").isNotNull()),
            "target.order_id = source.order_id"
        )
        .whenMatchedDelete(condition="source.op = 'd'")
        .whenMatchedUpdateAll(condition="source.op != 'd'")
        .whenNotMatchedInsertAll(condition="source.op != 'd'")
        .execute()
    )
    batch.show(truncate=False)


query = (
    value.writeStream
    .format("delta")
    .outputMode("append")
    .option("checkpointLocation", checkpoint_location)
    .foreachBatch(merge_batch_into)
    .start()
)

query.awaitTermination()
