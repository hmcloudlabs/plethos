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

# Checks that the new version bumps the previous version correctly
check_version_bump() {
  status=$(curl --silent --output /tmp/latest-release.json --write-out '%{http_code}' \
    --header "Authorization: token $CODEBERG_TOKEN" "$CI_FORGE_URL/api/v1/repos/$CI_REPO/releases/latest")
  if [ "$status" = 404 ]; then return 0; fi
  if [ "$status" != 200 ]; then
    echo "Couldn't fetch the latest release (HTTP $status)" >&2
    return 1
  fi

  previous=$(jq -r .tag_name /tmp/latest-release.json)
  previous=${previous##*-v}
  major=${previous%%.*}
  minor=${previous#*.}
  minor=${minor%%.*}
  patch=${previous##*.}

  next_major="$((major + 1)).0.0"
  next_minor="$major.$((minor + 1)).0"
  next_patch="$major.$minor.$((patch + 1))"
  if [ "$1" != "$next_major" ] && [ "$1" != "$next_minor" ] && [ "$1" != "$next_patch" ]; then
    echo "$1 isn't a valid bump of the latest release $previous" >&2
    return 1
  fi
}

# Creates the release and its tag for the given version
create_release() {
  tag="plethos-v$1"
  curl --fail --request POST "$CI_FORGE_URL/api/v1/repos/$CI_REPO/releases" \
    --header "Authorization: token $CODEBERG_TOKEN" --header "Content-Type: application/json" \
    --data "$(jq -n --arg tag "$tag" --arg ref "$CI_COMMIT_SHA" --arg name "Plethos v$1" --arg body "$(changelog_section "$1")" \
      '{tag_name:$tag, target_commitish:$ref, name:$name, body:$body}')"
}
