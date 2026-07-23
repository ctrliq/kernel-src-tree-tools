from kt.ktlib.commit_header import CommitHeader


def test_from_commit_body():
    commit_body = """
jira VULN-181881
cve-bf CVE-2026-31431
commit-author Yucheng Lu <kanolyc@gmail.com>
commit 5db6ef9847717329f12c5ea8aba7e9f588a980c0

authencesn requires either a zero authsize or an authsize of at least
4 bytes because the ESN encrypt/decrypt paths always move 4 bytes of
high-order sequence number data at the end of the authenticated data.

While crypto_authenc_esn_setauthsize() already rejects explicit
non-zero authsizes in the range 1..3, crypto_authenc_esn_create()
still copied auth->digestsize into inst->alg.maxauthsize without
validating it.  The AEAD core then initialized the tfm's default
authsize from that value.

As a result, selecting an ahash with digest size 1..3, such as
cbcmac(cipher_null), exposed authencesn instances whose default
authsize was invalid even though setauthsize() would have rejected the
same value.  AF_ALG could then trigger the ESN tail handling with a
too-short tag and hit an out-of-bounds access.

Reject authencesn instances whose ahash digest size is in the invalid
non-zero range 1..3 so that no tfm can inherit an unsupported default
authsize.

Fixes: f15f05b0a5de ("crypto: ccm - switch to separate cbcmac driver")
    Cc: stable@kernel.org
    Reported-by: Yifan Wu <yifanwucs@gmail.com>
    Reported-by: Juefei Pu <tomapufckgml@gmail.com>
    Co-developed-by: Yuan Tan <yuantan098@gmail.com>
    Signed-off-by: Yuan Tan <yuantan098@gmail.com>
    Suggested-by: Xin Liu <bird@lzu.edu.cn>
    Tested-by: Yuhang Zheng <z1652074432@gmail.com>
    Reviewed-by: Eric Biggers <ebiggers@kernel.org>
    Signed-off-by: Yucheng Lu <kanolyc@gmail.com>
    Signed-off-by: Ren Wei <n05ec@lzu.edu.cn>
    Signed-off-by: Herbert Xu <herbert@gondor.apana.org.au>

"""
    commit_header = CommitHeader.from_commit_body(commit_body=commit_body)
    result = commit_header.to_str()
    assert result == commit_body
