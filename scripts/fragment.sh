#!/bin/bash
file="$1"; id="$2"
lines=$(tail -n +3 "$file")                 # skip N + comment
# split into Bash arrays
mapfile -t atoms <<<"$lines"
n=${#atoms[@]}

# Build adjacency (Å < 1.8)
declare -A seen
cluster=()
for ((i=0;i<n;i++)); do
  read -r si xi yi zi <<<"${atoms[i]}"
  for ((j=i+1;j<n;j++)); do
    read -r sj xj yj zj <<<"${atoms[j]}"
    dx=$(echo "$xi-$xj" | bc -l); dy=$(echo "$yi-$yj" | bc -l); dz=$(echo "$zi-$zj" | bc -l)
    dist=$(echo "sqrt($dx*$dx+$dy*$dy+$dz*$dz)" | bc -l)
    (( $(echo "$dist<1.8" | bc -l) )) && seen[$i,$j]=1 && seen[$j,$i]=1
  done
done
# BFS from atom 0 → clusterA
queue=(0); clusterA[0]=1
while ((${#queue[@]})); do
  i=${queue[0]}; queue=("${queue[@]:1}")
  for ((j=0;j<n;j++)); do
    [[ ${seen[$i,$j]} && -z ${clusterA[$j]} ]] && clusterA[$j]=1 && queue+=($j)
  done
done
# dump files
{
  echo "${#clusterA[@]}"
  echo "$id A"
  for ((i=0;i<n;i++)); do [[ ${clusterA[$i]} ]] && echo "${atoms[i]}"; done
} > "${id}_A.xyz"
{
  echo "$((n-${#clusterA[@]}))"
  echo "$id B"
  for ((i=0;i<n;i++)); do [[ -z ${clusterA[$i]} ]] && echo "${atoms[i]}"; done
} > "${id}_B.xyz"