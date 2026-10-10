REGISTRY="${CI_FORGE_URL#*://}"
REGISTRY_IMAGE="$REGISTRY/$(echo "$CI_REPO_OWNER" | tr '[:upper:]' '[:lower:]')"
CHART=charts/plethos/Chart.yaml

# Extracts the latest changelog section based on section starting with a '##' heading
changelog_section() {
  awk -v version="[$1]" '
    /^## / { if (found) exit; if (index($0, version)) { found = 1; next } }
    found
  ' CHANGELOG.md
}

# Extracts the release version in Chart.yaml after checking that the chart's appVersion
# matches it and CHANGELOG.md has an entry for it
release_version() {
  version=$(sed -nE 's/^version: *"?([^"]+)"?$/\1/p' "$CHART")
  app_version=$(sed -nE 's/^appVersion: *"?([^"]+)"?$/\1/p' "$CHART")
  if [ "$app_version" != "$version" ]; then
    echo "$CHART's appVersion is \"$app_version\", but its version is \"$version\"" >&2
    return 1
  fi

  if [ -z "$(changelog_section "$version")" ]; then
    echo "No CHANGELOG entry for $version" >&2
    return 1
  fi
  echo "$version"
}

# Creates the release and its tag for the given version
create_release() {
  tag="plethos-v$1"
  curl --fail --request POST "$CI_FORGE_URL/api/v1/repos/$CI_REPO/releases" \
    --header "Authorization: token $CODEBERG_TOKEN" --header "Content-Type: application/json" \
    --data "$(jq -n --arg tag "$tag" --arg ref "$CI_COMMIT_SHA" --arg name "Plethos v$1" --arg body "$(changelog_section "$1")" \
      '{tag_name:$tag, target_commitish:$ref, name:$name, body:$body}')"
}
