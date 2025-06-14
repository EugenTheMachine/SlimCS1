# Modified from Segment Anything Model (SAM)
# Copyright (c) Meta Platforms, Inc. and affiliates.
# Licensed under the Apache License, Version 2.0

from functools import partial

import torch
from torch.nn import functional as F

from segment_anything.modeling import (
    ImageEncoderViT,
    MaskDecoder,
    PromptEncoder,
    Sam,
    TwoWayTransformer,
)


def build_sam_vit_h(checkpoint=None, image_size=1024):
    return _build_sam(
        encoder_embed_dim=1280,
        encoder_depth=32,
        encoder_num_heads=16,
        encoder_global_attn_indexes=[7, 15, 23, 31],
        image_size=image_size,
        checkpoint=checkpoint,
    )


def build_sam_vit_l(checkpoint=None, image_size=1024):
    return _build_sam(
        encoder_embed_dim=1024,
        encoder_depth=24,
        encoder_num_heads=16,
        encoder_global_attn_indexes=[5, 11, 17, 23],
        image_size=image_size,
        checkpoint=checkpoint,
    )


def build_sam_vit_b(checkpoint=None, image_size=1024):
    return _build_sam(
        encoder_embed_dim=768,
        encoder_depth=12,
        encoder_num_heads=12,
        encoder_global_attn_indexes=[2, 5, 8, 11],
        image_size=image_size,
        checkpoint=checkpoint,
    )

def build_sam_vit_p50(checkpoint=None, image_size=1024):
    return _build_sam(
        encoder_embed_dim=384,
        # mlp_dim=1536,
        encoder_depth=12,
        encoder_num_heads=12,
        encoder_global_attn_indexes=[2, 5, 8, 11],
        image_size=image_size,
        checkpoint=checkpoint,
    )

def build_sam_vit_p77(checkpoint=None, image_size=1024):
    return _build_sam(
        encoder_embed_dim=168,
        # mlp_dim=696,
        encoder_depth=12,
        encoder_num_heads=12,
        encoder_global_attn_indexes=[2, 5, 8, 11],
        image_size=image_size,
        checkpoint=checkpoint,
    )


# sam_model_registry = {
#     "default": build_sam_vit_h,
#     "vit_h": build_sam_vit_h,
#     "vit_l": build_sam_vit_l,
#     "vit_b": build_sam_vit_b,
# }
sam_model_registry = {
    "default": build_sam_vit_h,
    "vit_h": build_sam_vit_h,
    "vit_l": build_sam_vit_l,
    "vit_b": build_sam_vit_b,
    "vit_p50": build_sam_vit_p50,
    "vit_p77": build_sam_vit_p77,
}


def _build_sam(
    encoder_embed_dim,
    encoder_depth,
    encoder_num_heads,
    encoder_global_attn_indexes,
    image_size,
    checkpoint=None,
):
    prompt_embed_dim = 256
    # image_size = 512
    vit_patch_size = 16
    image_embedding_size = image_size // vit_patch_size
    sam = Sam(
        image_encoder=ImageEncoderViT(
            depth=encoder_depth,
            embed_dim=encoder_embed_dim,
            img_size=image_size,
            mlp_ratio=4,
            norm_layer=partial(torch.nn.LayerNorm, eps=1e-6),
            num_heads=encoder_num_heads,
            patch_size=vit_patch_size,
            qkv_bias=True,
            use_rel_pos=True,
            global_attn_indexes=encoder_global_attn_indexes,
            window_size=14,
            out_chans=prompt_embed_dim,
        ),
        prompt_encoder=PromptEncoder(
            embed_dim=prompt_embed_dim,
            image_embedding_size=(image_embedding_size, image_embedding_size),
            input_image_size=(image_size, image_size),
            mask_in_chans=16,
        ),
        mask_decoder=MaskDecoder(
            num_multimask_outputs=3,
            transformer=TwoWayTransformer(
                depth=2,
                embedding_dim=prompt_embed_dim,
                mlp_dim=2048,  # was 2048
                num_heads=8,
            ),
            transformer_dim=prompt_embed_dim,
            iou_head_depth=3,
            iou_head_hidden_dim=256,
        ),
        pixel_mean=[123.675, 116.28, 103.53],
        pixel_std=[58.395, 57.12, 57.375],
    )
    sam.eval()
    if checkpoint is not None:
        with open(checkpoint, "rb") as f:
            state_dict = torch.load(f, weights_only=True)
        try:
            sam.load_state_dict(state_dict)
        except RuntimeError:
            new_state_dict = load_from(
                sam, state_dict, image_size, vit_patch_size, encoder_global_attn_indexes
            )
            sam.load_state_dict(new_state_dict)
    return sam


def check_contain(key, except_strings):
    for strs in except_strings:
        if strs in key:
            return True
    return False


# https://github.com/hitachinsk/SAMed/blob/main/segment_anything/build_sam.py

# MIT License

# Copyright (c) 2023 Kaidong Zhang

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.


# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
def load_from(sam, state_dict, image_size, vit_patch_size, encoder_global_attn_indexes):
    sam_dict = sam.state_dict()
    except_strings = []
    new_state_dict = {}
    for k, v in state_dict.items():
        if k in sam_dict.keys() and not check_contain(k, except_strings):
            new_state_dict[k] = v
    pos_embed = new_state_dict["image_encoder.pos_embed"]
    token_size = int(image_size // vit_patch_size)
    if pos_embed.shape[1] != token_size:
        pos_embed = pos_embed.permute(0, 3, 1, 2)  # [b, c, h, w]
        pos_embed = F.interpolate(
            pos_embed, (token_size, token_size), mode="bilinear", align_corners=True
        )
        pos_embed = pos_embed.permute(0, 2, 3, 1)  # [b, h, w, c]
        new_state_dict["image_encoder.pos_embed"] = pos_embed
        rel_pos_keys = [k for k in sam_dict.keys() if "rel_pos" in k]
        global_rel_pos_keys = []
        for k in rel_pos_keys:
            flag = any(
                [(str(j) == k.split(".")[2]) for j in encoder_global_attn_indexes]
            )
            if flag:
                global_rel_pos_keys.append(k)
        # global_rel_pos_keys = [k for k in rel_pos_keys if "2" in k or "5" in k or "8" in k or "11" in k]
        for k in global_rel_pos_keys:
            rel_pos_params = new_state_dict[k]
            h, w = rel_pos_params.shape
            rel_pos_params = rel_pos_params.unsqueeze(0).unsqueeze(0)
            rel_pos_params = F.interpolate(
                rel_pos_params,
                (token_size * 2 - 1, w),
                mode="bilinear",
                align_corners=True,
            )
            new_state_dict[k] = rel_pos_params[0, 0, ...]
    sam_dict.update(new_state_dict)
    return sam_dict


if __name__ == "__main__":
    pass
