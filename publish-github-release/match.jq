def expected_asset:
  .name as $name | .digest as $digest |
  any($assets[0][]; .name == $name and .digest == $digest);

if $phase == "draft" then
  length == 1 and all(.[0].assets[]; .state == "uploaded" and expected_asset)
else
  length == 1 and
  ([.[0].assets[] | select(.state == "uploaded") | {name, digest}] | sort_by(.name)) ==
  ($assets[0] | sort_by(.name))
end
