REGISTRY="${CI_FORGE_URL#*://}"
REGISTRY_IMAGE="$REGISTRY/$(echo "$CI_REPO_OWNER" | tr '[:upper:]' '[:lower:]')"

# Builds the image of the given component and pushes it to Codeberg's registry
build_and_push() {
  image="$REGISTRY_IMAGE/plethos-$1"
  echo "$CODEBERG_TOKEN" | buildah login --username "$CODEBERG_USER" --password-stdin "$REGISTRY"
  buildah build --file "components/$1/Dockerfile" --tag "$image:$2" --tag "$image:latest" .
  buildah push "$image:$2"
  buildah push "$image:latest"
}

# Extracts the latest changelog section based on section starting with a '##' heading
changelog_section() {
  if [ "$1" = chart ]; then file=CHANGELOG.md; else file="components/$1/CHANGELOG.md"; fi

  awk -v version="[$2]" '
    /^## / { if (found) exit; if (index($0, version)) { found = 1; next } }
    found
  ' "$file"
}

# Creates the release and its tag for the given component and version
create_release() {
  tag="$1-v$2"
  notes="$(changelog_section "$1" "$2")"
  if [ -z "$notes" ]; then
    echo "No CHANGELOG entry for $tag"
    return 1
  fi

  case "$1" in
    portal) title="Plethos Portal v$2" ;;
    controller) title="Plethos Controller v$2" ;;
    chart) title="Plethos Helm Chart v$2" ;;
  esac

  curl --fail --request POST "$CI_FORGE_URL/api/v1/repos/$CI_REPO/releases" \
    --header "Authorization: token $CODEBERG_TOKEN" --header "Content-Type: application/json" \
    --data "$(jq -n --arg tag "$tag" --arg ref "$CI_COMMIT_SHA" --arg name "$title" --arg body "$notes" \
      '{tag_name:$tag, target_commitish:$ref, name:$name, body:$body}')"
}
