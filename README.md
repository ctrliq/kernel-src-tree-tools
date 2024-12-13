# kernel-src-tree-tools
Welcome to the CIQ kernel-src-tree-tools package. This is a collection of scripts we at CIQ use to interact with our Kernel Source Tree.

These are just scripts we have used internally and have decided to share with the community to encourage other to contribute to our requirements more easily.

## ciq-cherry-pick
This script is used to cherry-pick a commit from a remote repository to the current branch.
It is a wrapper around `git cherry-pick -nsx <sha>` command but sets up the incoming commit with the header information we require.
The script will also prep the commit message in the event of merge conflict so the Engineer can easily resolve the conflict and add in their `upstream-diff` comment into the commit message with everything else in the header already in place

Note: We also indent the lines of the commit 

### Example: CVE-2022-3565 for jira VULN-168
This is for cherry-picking a commit for `CVE-2024-1234` that is associated to ticket `jira VULN-1234`
```
$ ciq-cherry-pick --ticket "VULN-168" --ciq-tag "cve CVE-2022-3565" 2568a7e0832ee30b0a351016d03062ab4e0e0a3f
```

This will produce a comment message like:
https://github.com/ctrliq/kernel-src-tree/commit/8998df1511050f09e5ee1379e4c099cacdde7434
```
mISDN: fix use-after-free bugs in l1oip timer handlers

jira VULN-168
cve CVE-2022-3565
commit-author Duoming Zhou <duoming@zju.edu.cn>
commit 2568a7e0832ee30b0a351016d03062ab4e0e0a3f

The l1oip_cleanup() traverses the l1oip_ilist and calls
release_card() to cleanup module and stack. However,
release_card() calls del_timer() to delete the timers
such as keep_tl and timeout_tl. If the timer handler is
running, the del_timer() will not stop it and result in
UAF bugs. One of the processes is shown below:

    (cleanup routine)          |        (timer handler)
release_card()                 | l1oip_timeout()
 ...                           |
 del_timer()                   | ...
 ...                           |
 kfree(hc) //FREE              |
                               | hc->timeout_on = 0 //USE

Fix by calling del_timer_sync() in release_card(), which
makes sure the timer handlers have finished before the
resources, such as l1oip and so on, have been deallocated.

What's more, the hc->workq and hc->socket_thread can kick
those timers right back in. We add a bool flag to show
if card is released. Then, check this flag in hc->workq
and hc->socket_thread.

Fixes: 3712b42d4b1b ("Add layer1 over IP support")
        Signed-off-by: Duoming Zhou <duoming@zju.edu.cn>
        Reviewed-by: Leon Romanovsky <leonro@nvidia.com>
        Signed-off-by: David S. Miller <davem@davemloft.net>
(cherry picked from commit 2568a7e0832ee30b0a351016d03062ab4e0e0a3f)
        Signed-off-by: Greg Rose <g.v.rose@ciq.com>
```


## kernel_build.sh and kernel_recompile_kabi.sh
These are two scripts we use to compile, kabi test, and install the kernel to a VM of associated Major and Minor Release.

### Assumed Structure of kernel workspace directory
Currently we all internally work with the same common craoss HOST:VM mounted directory's containing a git repo design like the following:
```
<workdir>
  |- kernel-src-tree
  |- kernel-src-tree-tools
  |- kernel-dist-git
```
The Dist git can be found here: https://github.com/ciq-rocky-lts/kernel

You can find additional information on the kernel-src-tree wiki page:
https://github.com/ctrliq/kernel-src-tree/wiki

### kernel_build.sh
This is the full script that end with the engineer ready to reboot the VM into the new kernel.

### kernel_recompile_kabi.sh
Will only recompile the kernel and check the KABI.
