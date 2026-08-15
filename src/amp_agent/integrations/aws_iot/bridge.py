import json
import logging
import os
import signal
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from awscrt import mqtt
from awsiot import mqtt_connection_builder


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("amp-iot-bridge")


IOT_ENDPOINT = os.environ["IOT_ENDPOINT"]
IOT_CA = os.environ["IOT_CA"]
IOT_CERT = os.environ["IOT_CERT"]
IOT_KEY = os.environ["IOT_KEY"]

IOT_CLIENT_ID = os.getenv("IOT_CLIENT_ID", "amp-ubuntu")
IOT_COMMAND_TOPIC = os.getenv(
    "IOT_COMMAND_TOPIC",
    "amp/ubuntu/command",
)
IOT_RESPONSE_PREFIX = os.getenv(
    "IOT_RESPONSE_PREFIX",
    "amp/ubuntu/response",
)

AMP_VOICE_URL = os.getenv(
    "AMP_VOICE_URL",
    "http://127.0.0.1:8000/voice",
)

VOICE_SECRET_PATH = os.getenv(
    "AMP_VOICE_SECRET_PATH",
    os.path.expanduser(
        "~/amp/app/secrets/amp_voice_api_key.txt"
    ),
)


running = True


def load_voice_key() -> str:
    with open(
        VOICE_SECRET_PATH,
        "r",
        encoding="utf-8",
    ) as file:
        value = file.read().strip()

    if not value:
        raise RuntimeError("AMP voice secret vazio.")

    return value


def call_voice(
    text: str,
    request_id: str,
) -> dict:
    voice_key = load_voice_key()

    body = {
        "text": text,
        "source": "alexa",
        "request_id": request_id,
        "timestamp": int(time.time()),
    }

    request = Request(
        AMP_VOICE_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-AMP-Voice-Key": voice_key,
        },
        method="POST",
    )

    try:
        with urlopen(
            request,
            timeout=6,
        ) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)

    except HTTPError as exc:
        logger.exception(
            "AMP /voice retornou HTTP %s",
            exc.code,
        )

        return {
            "ok": False,
            "speech": (
                "O AMP recusou a solicitação."
            ),
        }

    except URLError:
        logger.exception(
            "Não foi possível acessar o AMP."
        )

        return {
            "ok": False,
            "speech": (
                "O servidor AMP está indisponível."
            ),
        }

    except Exception:
        logger.exception(
            "Erro inesperado ao chamar /voice."
        )

        return {
            "ok": False,
            "speech": (
                "Ocorreu um erro ao acessar o AMP."
            ),
        }


def publish_response(
    mqtt_connection,
    request_id: str,
    response: dict,
) -> None:
    topic = f"{IOT_RESPONSE_PREFIX}/{request_id}"

    payload = {
        "request_id": request_id,
        "ok": bool(response.get("ok")),
        "speech": str(
            response.get(
                "speech",
                "Não foi possível obter uma resposta.",
            )
        ),
    }

    execution_id = response.get("execution_id")

    if execution_id:
        payload["execution_id"] = execution_id

    mqtt_connection.publish(
        topic=topic,
        payload=json.dumps(
            payload,
            ensure_ascii=False,
        ),
        qos=mqtt.QoS.AT_LEAST_ONCE,
    )

    logger.info(
        "Resposta publicada em %s",
        topic,
    )


def on_message(
    topic,
    payload,
    dup,
    qos,
    retain,
    **kwargs,
):
    del dup, qos, retain

    logger.info(
        "Mensagem recebida em %s",
        topic,
    )

    try:
        command = json.loads(
            payload.decode("utf-8")
        )

        request_id = str(
            command["request_id"]
        ).strip()

        text = str(
            command["text"]
        ).strip()

        if not request_id:
            raise ValueError(
                "request_id vazio"
            )

        if not text:
            raise ValueError(
                "text vazio"
            )

    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        logger.exception(
            "Comando MQTT inválido."
        )
        return

    logger.info(
        "Processando request_id=%s",
        request_id,
    )

    response = call_voice(
        text=text,
        request_id=request_id,
    )

    publish_response(
        mqtt_connection=MQTT_CONNECTION,
        request_id=request_id,
        response=response,
    )


def stop_handler(signum, frame):
    del signum, frame

    global running
    running = False


signal.signal(
    signal.SIGINT,
    stop_handler,
)
signal.signal(
    signal.SIGTERM,
    stop_handler,
)


MQTT_CONNECTION = mqtt_connection_builder.mtls_from_path(
    endpoint=IOT_ENDPOINT,
    cert_filepath=IOT_CERT,
    pri_key_filepath=IOT_KEY,
    ca_filepath=IOT_CA,
    client_id=IOT_CLIENT_ID,
    clean_session=False,
    keep_alive_secs=30,
)


def main() -> int:
    logger.info(
        "Conectando ao AWS IoT Core..."
    )

    MQTT_CONNECTION.connect().result()

    logger.info(
        "Conectado como %s",
        IOT_CLIENT_ID,
    )

    subscribe_future, _ = MQTT_CONNECTION.subscribe(
        topic=IOT_COMMAND_TOPIC,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=on_message,
    )

    subscribe_result = subscribe_future.result()

    logger.info(
        "Assinado %s com QoS %s",
        IOT_COMMAND_TOPIC,
        subscribe_result["qos"],
    )

    try:
        while running:
            time.sleep(1)

    finally:
        logger.info(
            "Desconectando do AWS IoT Core..."
        )

        MQTT_CONNECTION.disconnect().result()

    return 0


if __name__ == "__main__":
    sys.exit(main())
