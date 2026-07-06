#!/bin/bash

# Load generator — fires concurrent inference requests to move dashboard metrics
# Usage: ./loadgen.sh [duration_seconds] [concurrency]

DURATION=${1:-120}
CONCURRENCY=${2:-20}

VAI_KEY=$(cat /Users/kboumedh/clients/OCPAI/vai.key)
MAI_KEY=$(cat /Users/kboumedh/clients/OCPAI/mai.key)

TARGETS=(
  "https://maas.apps.vai.karmab-azure.sysdeseng.com/my-first-model/qwen3-0-6b/v1/chat/completions|Qwen/Qwen3-0.6B|$VAI_KEY"
  "https://maas.apps.mai.karmab.sysdeseng.com/my-first-model/qwen3-0-6b/v1/chat/completions|Qwen/Qwen3-0.6B|$MAI_KEY"
  "https://maas.apps.mai.karmab.sysdeseng.com/qwen3-14b/qwen3-14b/v1/chat/completions|Qwen/Qwen3-14B|$MAI_KEY"
)

PROMPTS=(
  "Write a detailed essay about the history of computing from the 1940s to today"
  "Explain quantum mechanics to a 10 year old in great detail"
  "Write a short story about a robot learning to play guitar"
  "Describe every planet in the solar system and their moons"
  "Explain the theory of relativity and its implications for modern physics"
  "Write a comprehensive guide to machine learning algorithms"
  "Describe the evolution of programming languages from Fortran to Rust"
  "Write about the history of the internet from ARPANET to today"
)

send_request() {
  local url model key prompt
  IFS='|' read -r url model key <<< "$1"
  prompt="${PROMPTS[$((RANDOM % ${#PROMPTS[@]}))]}"
  curl -sk --max-time 120 "$url" \
    -H "Authorization: Bearer $key" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"$prompt\"}],\"max_tokens\":2048}" \
    > /dev/null 2>&1
}

echo "Firing $CONCURRENCY concurrent requests across ${#TARGETS[@]} targets for ${DURATION}s"
echo "Targets:"
for t in "${TARGETS[@]}"; do echo "  $(echo "$t" | cut -d'|' -f1,2 --output-delimiter=' ')"; done
echo ""

END=$((SECONDS + DURATION))
COUNT=0

while [ $SECONDS -lt $END ]; do
  for i in $(seq 1 $CONCURRENCY); do
    target="${TARGETS[$((RANDOM % ${#TARGETS[@]}))]}"
    send_request "$target" &
  done
  COUNT=$((COUNT + CONCURRENCY))
  echo "[$(date +%H:%M:%S)] Fired $COUNT requests total"
  # wait for batch to finish before next round
  wait
done

echo "Done. Sent $COUNT requests in ${DURATION}s"
