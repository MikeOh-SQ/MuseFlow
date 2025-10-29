# MuseFlow

## Windows에서 Muse 2 데이터 수집하기

이 저장소에는 [BrainFlow](https://brainflow.org) 라이브러리를 사용하여 Bluetooth를 통해 Muse 2 헤드셋에 직접 연결하는 Windows용
보조 스크립트가 포함되어 있습니다. Raspberry Pi에서 사용하던 설정과 동일한 동작을 목표로 하지만, Windows Bluetooth 드라이버의 특
성을 반영해 기본값과 워크플로우가 조정되어 있습니다. 2024년 업데이트로 [BlueMuse](https://github.com/kowalej/BlueMuse)의 원격 제어
기능을 GUI에 통합해 Windows Bluetooth 설정에서 헤드셋을 바로 추가하지 못할 때도 BlueMuse를 통해 검색·연결을 수행할 수 있습니다.

### 사전 준비

* BrainFlow Python 패키지와 의존성을 설치합니다:

      pip install brainflow

* [BlueMuse GitHub 릴리스](https://github.com/kowalej/BlueMuse/releases)에서 최신 Windows 설치 파일을 내려받아 설치합니다.
  * BlueMuse를 한 번 실행해 **Settings → Remote Control → Enable**을 눌러 원격 제어 서버를 활성화합니다.
  * BlueMuse Remote Control의 기본 주소는 `http://127.0.0.1:5000`이며, GUI에서 다른 포트로 바뀌었을 경우 직접 수정할 수 있습니다.

* BlueMuse에서 Muse 2 헤드셋을 한 번 스캔하여 목록에 표시되도록 한 뒤, 장치의 Bluetooth MAC 주소를 확인합니다.
  GUI의 **MAC 입력** 버튼을 사용하면 목록에서 선택한 헤드셋의 MAC을 즉시 채울 수 있으므로 Windows 설정에서 별도로 페어링할 필요가
  없습니다.

### GUI 사용 방법

1. 저장소 루트에서 다음 명령으로 GUI를 실행합니다.

   ```bash
   python scripts/muse2_windows_stream.py
   ```

2. **BlueMuse 연동** 섹션에서 다음 작업을 수행합니다.
   * **실행 파일 경로**에 `BlueMuse.exe` 경로를 입력하거나 **찾아보기** 버튼을 눌러 선택합니다.
   * **원격 제어 주소**가 BlueMuse Remote Control 설정과 일치하는지 확인합니다.
   * 한 번 경로를 지정하면 GUI가 녹화 시작 시 BlueMuse를 자동으로 실행하고 원격 제어 서버가 준비될 때까지 기다립니다. 필요하다면 **BlueMuse 실행** 버튼으로 수동 실행도 가능합니다.
   * **스캔 시작** → **목록 새로고침** 순으로 눌러 Muse 2가 검색되는지 확인합니다.
   * 목록에서 헤드셋을 선택하고 **MAC 입력** 버튼을 눌러 BrainFlow 설정에 자동으로 채웁니다.
   * "녹화 시 BlueMuse로 자동 연결/해제" 옵션이 기본적으로 활성화되어 있으므로, **녹화 시작**을 누르면 GUI가 BlueMuse 원격 제어 코드를
     통해 헤드셋 연결과 해제를 자동으로 처리합니다. 필요에 따라 체크박스를 해제하면 수동으로 BlueMuse를 제어할 수도 있습니다.

3. 필요한 경우 Serial Port, IP 설정, 녹화 시간, BrainFlow 버퍼 크기 등을 조정합니다. 기본값은 대부분의 상황에서 바로 사용할 수 있
   도록 설정되어 있습니다.

4. 출력 CSV 파일 경로를 선택하고 **녹화 시작** 버튼을 누르면 GUI가 필요할 경우 BlueMuse를 자동으로 실행한 후 원격 제어 API를 통해
   Bluetooth 연결을 확립하고 BrainFlow 스트리밍을 시작합니다. 녹화가 끝나면 자동으로 BlueMuse 연결을 해제하고, CSV 파일이 저장된 뒤
   요약 정보가 창 하단 로그에 표시됩니다.

5. **채널 요약 출력** 옵션을 선택하면 각 채널의 최소/최대/평균값 요약이 함께 표시됩니다.

### BlueMuse 통합 팁

* BlueMuse Remote Control 서버가 실행되고 있지 않으면 GUI에서 BlueMuse 관련 버튼을 눌렀을 때 오류가 표시됩니다. 이 경우 BlueMuse
  앱에서 **Remote Control → Enable** 상태를 다시 확인하세요.
* "녹화 시 BlueMuse로 자동 연결/해제"가 활성화된 상태에서 오류가 발생하면 BlueMuse 앱의 장치 목록이 실제로 업데이트되는지 확인하
  고, 필요하다면 BlueMuse에서 직접 연결/해제 버튼을 눌러 상태를 초기화한 뒤 다시 시도하세요.
* 회사 네트워크 또는 방화벽 소프트웨어가 로컬 HTTP 통신을 차단할 경우 `원격 제어 주소` 항목을 통해 허용된 포트로 조정하거나, 방화벽
  예외 목록에 BlueMuse를 추가해야 합니다.
* BlueMuse의 엔드포인트 구조는 릴리스에 따라 달라질 수 있습니다. 기본 주소에서 오류가 발생하면 BlueMuse 릴리스 노트를 참고해 GUI의
  주소 값을 수정한 뒤 **상태 확인** 버튼으로 응답을 점검하세요.
