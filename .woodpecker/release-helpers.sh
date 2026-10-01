REGISTRY="${CI_FORGE_URL#*://}"
REGISTRY_IMAGE="$REGISTRY/$(echo "$CI_REPO_OWNER" | tr '[:upper:]' '[:lower:]')"

build_and_push() {
  image="$REGISTRY_IMAGE/plethos-$1"
  echo "$CODEBERG_TOKEN" | buildah login --username "$CODEBERG_USER" --password-stdin "$REGISTRY"
  buildah build --file "components/$1/Dockerfile" --tag "$image:$2" --tag "$image:latest" .
  buildah push "$image:$2"
  buildah push "$image:latest"
}
