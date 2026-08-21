#!/bin/bash
set -x

PR_BRANCH=$1
TARGET_BRANCH=$2
NEXT_BRANCH="$2-next"

if [ -z "$PR_BRANCH" ] || [ -z "$TARGET_BRANCH" ]; then
  echo "Usage: $0 <pr_branch> <target_branch>"
  exit 1
fi

# Check if all branches exist
git show-ref --verify --quiet refs/heads/"${PR_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Branch ${PR_BRANCH} does not exist."
  exit 1
fi

git show-ref --verify --quiet refs/heads/"${TARGET_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Branch ${TARGET_BRANCH} does not exist."
  exit 1
fi

git show-ref --verify --quiet refs/heads/"${NEXT_BRANCH}"
if [ $? -ne 0 ] ; then
  echo "Branch ${NEXT_BRANCH} does not exist."
  exit 1
fi


makefile_version() {
  local makefile
  makefile=$(git show "$1:Makefile") || return 1
  local major minor sublevel
  major=$(echo "$makefile" | sed -n 's/^VERSION = //p')
  minor=$(echo "$makefile" | sed -n 's/^PATCHLEVEL = //p')
  sublevel=$(echo "$makefile" | sed -n 's/^SUBLEVEL = //p')
  [ -n "$major" ] && [ -n "$minor" ] && [ -n "$sublevel" ] && echo "${major}.${minor}.${sublevel}"
}

PAST_VERSION=$(makefile_version "${TARGET_BRANCH}")
if [ -z "$PAST_VERSION" ]; then
  echo "Failed to read kernel version from Makefile on ${TARGET_BRANCH}"
  exit 1
fi

PAST_VERSION_BRANCH="ciq-${PAST_VERSION}"
echo "PAST_VERSION: $PAST_VERSION"
echo "PAST_VERSION_BRANCH: $PAST_VERSION_BRANCH"

NEW_VERSION=$(makefile_version "${PR_BRANCH}")
if [ -z "$NEW_VERSION" ]; then
  echo "Failed to read kernel version from Makefile on ${PR_BRANCH}"
  exit 1
fi

LAST_TAG=$(git describe --tags --abbrev=0 "${TARGET_BRANCH}")
if [ -z "$LAST_TAG" ]; then
  echo "Failed to get tag from ${TARGET_BRANCH}"
  exit 1
fi
TAG_PREFIX=$(echo "$LAST_TAG" | awk -F '-' '{print $1}')
NEW_CIQ_TAG="${TAG_PREFIX}-${NEW_VERSION}-1"
# merge PR branch into next branch
set +x

echo "Commands expected to run (This is in the event it fails during the run)"
echo "git checkout \"${NEXT_BRANCH}\""
echo "git pull origin \"${NEXT_BRANCH}\""
echo "git merge --ff-only \"${PR_BRANCH}\""
echo "git push origin \"${NEXT_BRANCH}\""
echo "git branch -m \"${TARGET_BRANCH}\" \"${PAST_VERSION_BRANCH}\""
echo "git push origin :\"${TARGET_BRANCH}\" \"${PAST_VERSION_BRANCH}\""
echo "git push origin -u \"${PAST_VERSION_BRANCH}\""
echo "git branch -m \"${NEXT_BRANCH}\" \"${TARGET_BRANCH}\""
echo "git push origin :\"${NEXT_BRANCH}\" \"${TARGET_BRANCH}\""
echo "git push origin -u \"${TARGET_BRANCH}\""
echo "git tag \"${NEW_CIQ_TAG}\" \"${TARGET_BRANCH}\""
echo "git push origin \"${NEW_CIQ_TAG}\""

echo "git checkout $NEXT_BRANCH"
git checkout "${NEXT_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Failed to checkout ${NEXT_BRANCH}."
  exit 1
fi

echo "git pull origin $NEXT_BRANCH"
git pull origin "${NEXT_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Failed to pull ${NEXT_BRANCH}."
  exit 1
fi

echo "git merge --ff-only ${PR_BRANCH}"
git merge --ff-only "${PR_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Failed to merge ${PR_BRANCH} into ${NEXT_BRANCH}."
  exit 1
fi

echo "git push origin $NEXT_BRANCH"
git push origin "${NEXT_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Failed to push ${NEXT_BRANCH}."
  exit 1
fi

echo "Delete PR branch ${PR_BRANCH} locally and remotely"
echo "git push origin :${PR_BRANCH}"
git push origin :"${PR_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Failed to delete ${PR_BRANCH} remotely."
  exit 1
fi
git branch -d "${PR_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Failed to delete ${PR_BRANCH} locally."
  exit 1
fi


echo "git branch -m $TARGET_BRANCH $PAST_VERSION_BRANCH"
git branch -m "${TARGET_BRANCH}" "${PAST_VERSION_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Failed to rename ${TARGET_BRANCH} to ${PAST_VERSION_BRANCH}."
  exit 1
fi

echo "git push origin :$TARGET_BRANCH $PAST_VERSION_BRANCH"
git push origin :"${TARGET_BRANCH}" "${PAST_VERSION_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Failed to delete ${TARGET_BRANCH}."
  exit 1
fi

echo "git push origin -u $PAST_VERSION_BRANCH"
git push origin -u "${PAST_VERSION_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Failed to push ${PAST_VERSION_BRANCH}."
  exit 1
fi

echo "git branch -m $NEXT_BRANCH $TARGET_BRANCH"
git branch -m "${NEXT_BRANCH}" "${TARGET_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Failed to rename ${NEXT_BRANCH} to ${TARGET_BRANCH}."
  exit 1
fi

echo "git push origin :$NEXT_BRANCH $TARGET_BRANCH"
git push origin :"${NEXT_BRANCH}" "${TARGET_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Failed to delete ${NEXT_BRANCH}."
  exit 1
fi

echo "git push origin -u $TARGET_BRANCH"
git push origin -u "${TARGET_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Failed to push ${TARGET_BRANCH}."
  exit 1
fi

echo "git tag $NEW_CIQ_TAG $TARGET_BRANCH"
git tag "${NEW_CIQ_TAG}" "${TARGET_BRANCH}"
if [ $? -ne 0 ]; then
  echo "Failed to tag ${TARGET_BRANCH} with ${NEW_CIQ_TAG}."
  exit 1
fi

echo "git push origin $NEW_CIQ_TAG"
git push origin "${NEW_CIQ_TAG}"
if [ $? -ne 0 ]; then
  echo "Failed to push ${NEW_CIQ_TAG}."
  exit 1
fi
