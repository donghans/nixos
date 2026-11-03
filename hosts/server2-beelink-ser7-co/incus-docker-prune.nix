{pkgs, ...}: {
  # incus 인스턴스(LXC·VM) 안의 Docker 를 매시간 정리한다. 대상은 "docker 가 있는 실행 중 인스턴스"를
  # 자동으로 찾는다 — 새 LXC 를 만들어도 이 파일을 고칠 필요가 없다.
  #
  # 왜: 2026-11-03 실측으로 LXC 5개 안의 BuildKit 빌드 캐시가 합쳐 약 170GB 였다(genple-dev 43GB,
  # genple 23GB, genple-demo 16GB, dms 53GB 등; 한 번 정리하니 호스트 여유가 243 → 313GiB).
  # 이 안의 Docker 에는 자동 정리가 없어(호스트·VM 에만 있었다) 재빌드할 때마다 계속 쌓였다.
  # 쿼터·경보는 쌓이는 걸 막지 못하므로 쓰지 않고, 쌓이는 원인(캐시)을 짧은 주기로 비운다.
  #
  # 지우는 것: 1시간 넘은 dangling 이미지(어떤 컨테이너도 안 쓰는 것만), 빌드 캐시(최근 10GB 는 남김).
  # 안 지우는 것: 태그가 붙은 이미지, 볼륨, 실행·중지된 컨테이너가 쓰는 이미지.
  # 부작용: 정리된 캐시 단계는 다음 빌드 때 다시 실행된다(시간만 든다). 직전 빌드(태그 없는 이전
  # 이미지)로의 즉시 롤백은 불가.
  # 데몬 설정(daemon.json builder.gc)으로 하는 방법도 있으나 dockerd 재시작(=서비스 중단)이 필요해 타이머로 한다.
  systemd.services.incus-docker-prune = {
    description = "Prune Docker dangling images and build cache inside incus instances";
    after = ["incus-startup.service"];
    path = [pkgs.incus pkgs.coreutils pkgs.gawk];
    serviceConfig = {
      Type = "oneshot";
      Nice = 10;
    };
    script = ''
      for n in $(incus list -f csv -c ns | awk -F, '$2=="RUNNING"{print $1}'); do
        incus exec "$n" -- sh -c 'command -v docker >/dev/null 2>&1' || continue
        echo "== $n"
        incus exec "$n" -- sh -c '
          docker image prune -f --filter until=1h
          docker builder prune -f --keep-storage 10GB
        ' || echo "incus-docker-prune: $n 정리 실패, 다음으로 진행"
      done
    '';
  };

  systemd.timers.incus-docker-prune = {
    wantedBy = ["timers.target"];
    timerConfig = {
      OnCalendar = "hourly";
      RandomizedDelaySec = "5min";
    };
  };
}
