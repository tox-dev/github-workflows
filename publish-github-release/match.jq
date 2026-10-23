def metadata:
  .name == $title and .body == $body and .prerelease == $prerelease;

def expected_asset:
  .name as $name | .digest as $digest |
  any($assets[0][]; .name == $name and .digest == $digest);

def allowed_asset($draft):
  .name as $name |
  any($assets[0][]; .name == $name) and
  (if .state == "uploaded" then expected_asset else $draft end);

if $phase == "existing" then
  length <= 1 and all(.[];
    .draft as $draft |
    metadata and
    ([.assets[].name] | unique | length) == (.assets | length) and
    all(.assets[]; allowed_asset($draft)) and
    (.draft or (.assets | length) == ($assets[0] | length))
  )
elif $phase == "draft" then
  length == 1 and .[0].name == $title and .[0].body == $body and
  .[0].prerelease == $prerelease and all(.[0].assets[]; .state == "uploaded" and expected_asset)
else
  length == 1 and .[0].name == $title and .[0].body == $body and
  .[0].prerelease == $prerelease and
  ([.[0].assets[] | select(.state == "uploaded") | {name, digest}] | sort_by(.name)) ==
  ($assets[0] | sort_by(.name))
end
