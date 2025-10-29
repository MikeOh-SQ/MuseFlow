# MuseFlow

## Windows에서 Muse 2 데이터 수집하기

이 저장소에는 [BrainFlow](https://brainflow.org) 라이브러리를 사용하여 Bluetooth를 통해 Muse 2 헤드셋에 직접 연결하는 Windows용 보조 스크립트가 포함되어 있습니다. Raspberry Pi에서 사용하던 설정과 동일한 동작을 목표로 하지만, Windows Bluetooth 드라이버의 특성을 반영해 일부 기본값이 조정되어 있습니다.

### 사전 준비

* BrainFlow Python 패키지와 의존성을 설치합니다:

      pip install brainflow

* 스크립트를 실행하기 전에 Windows의 Bluetooth 설정에서 Muse 2 헤드셋을 페어링합니다. 장치 정보에 표시되는 Bluetooth MAC 주소를 메모해 두세요.

### 사용 방법

저장소 루트에서 스크립트를 실행하고 Muse 2의 MAC 주소를 인자로 전달합니다. 기본적으로 20초 동안 데이터를 수집한 후 CSV 파일로 저장합니다.

```bash
python scripts/muse2_windows_stream.py \
    --mac-address AA:BB:CC:DD:EE:FF \
    --duration 30 \
    --output muse_capture.csv
```

BrainFlow가 ``serial_port`` 필드에도 MAC 주소를 요구하는 경우, ``--serial-port`` 옵션을 사용해 동일한 값을 전달하세요.

``--show-summary`` 옵션을 사용하면 녹화가 끝난 뒤 채널별 요약 통계를 출력합니다.
