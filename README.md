# MuseFlow

## Windows에서 Muse 2 데이터 수집하기

이 저장소에는 [BrainFlow](https://brainflow.org) 라이브러리를 사용하여 Bluetooth를 통해 Muse 2 헤드셋에 직접 연결하는 Windows용 보조 스크립트가 포함되어 있습니다. Raspberry Pi에서 사용하던 설정과 동일한 동작을 목표로 하지만, Windows Bluetooth 드라이버의 특성을 반영해 일부 기본값이 조정되어 있습니다.

### 사전 준비

* BrainFlow Python 패키지와 의존성을 설치합니다:

      pip install brainflow

* 스크립트를 실행하기 전에 Windows의 Bluetooth 설정에서 Muse 2 헤드셋을 페어링합니다. 장치 정보에 표시되는 Bluetooth MAC 주소를 메모해 두세요.

### 사용 방법

1. 저장소 루트에서 다음 명령으로 GUI를 실행합니다.

   ```bash
   python scripts/muse2_windows_stream.py
   ```

2. 나타난 창에서 Muse 2의 Bluetooth MAC 주소를 입력합니다. Windows Bluetooth 설정 또는 Muse Manager 앱에서 확인할 수 있습니다.

3. 필요한 경우 Serial Port, IP 설정, 녹화 시간, BrainFlow 버퍼 크기 등을 조정합니다. 기본값은 대부분의 상황에서 바로 사용할 수 있도록 설정되어 있습니다.

4. 출력 CSV 파일 경로를 선택하고 **녹화 시작** 버튼을 누르면 스트리밍이 진행됩니다. 녹화가 끝나면 CSV 파일이 저장되고 요약 정보가 창 하단 로그에 표시됩니다.

5. **채널 요약 출력** 옵션을 선택하면 각 채널의 최소/최대/평균값 요약이 함께 표시됩니다.
