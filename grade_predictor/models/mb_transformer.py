import argparse
import logging
import numpy as np
import torch
import torch.nn as nn
import pytorch_lightning as pl
from einops import rearrange
from positional_encodings.torch_encodings import PositionalEncoding1D, PositionalEncoding2D, PositionalEncoding3D, Summer


class MB2016Transformer(pl.LightningModule):
    """MB Transformer with cleaner structure and improved readability."""

    EMBEDDING_SIZE = 128     # Must be even number
    TF_NHEADS = 2
    TF_LAYERS = 2
    TF_DROPOUT = 0.2
    TF_FF_SIZE = 128

    def __init__(self, data_config: dict, args: argparse.Namespace = None):
        super().__init__()
        self.data_config = data_config

        self.input_dim = int(np.prod(self.data_config["input_dims"]))
        self.output_dim = int(np.prod(self.data_config["output_dims"]))
        self.token_dict_size = self.data_config["token_dict_size"]
        self.max_sequence = self.data_config["max_sequence"]

        self.embedding_size = self.EMBEDDING_SIZE
        self.tf_nheads = self.TF_NHEADS
        self.tf_nlayers = self.TF_LAYERS
        self.tf_dropout = self.TF_DROPOUT
        self.tf_ff_size = self.TF_FF_SIZE
        self.tf_max_len = self.max_sequence

        self.loss_fn = nn.MSELoss()

        self.embedding = nn.Embedding(self.token_dict_size, self.embedding_size, max_norm=True)
        self.pos_embedding = nn.Embedding(4, self.embedding_size, max_norm=True)
        self.rel_x_embedding = nn.Embedding(22, self.embedding_size // 2, max_norm=True)
        self.rel_y_embedding = nn.Embedding(36, self.embedding_size // 2, max_norm=True)
        # self.pos_encoder_order = PositionalEncoding1D(self.embedding_size)
        #
        # position_dim = 3
        # w_dim = 11
        # h_dim = 19
        # pe_blank = torch.zeros(1, position_dim, w_dim, h_dim, self.embedding_size)
        # self.pos_encoder_3d = Summer(PositionalEncoding3D(self.embedding_size))(pe_blank)

        encoder_layer = nn.TransformerEncoderLayer(d_model=self.embedding_size, nhead=self.tf_nheads,
                                                   dropout=self.tf_dropout, dim_feedforward=self.tf_ff_size,
                                                   batch_first=True)
        self.transformer_encoder = nn.TransformerEncoder(encoder_layer, self.tf_nlayers)
        self.fc1 = nn.Linear(self.embedding_size*self.tf_max_len, 10)
        self.fc2 = nn.Linear(10, self.output_dim)

    def forward(self, data):
        xs = data['xs']
        order = data['order']
        rel_x_tokens = data['rel_x_tokens']
        rel_y_tokens = data['rel_y_tokens']
        rel_x = self.rel_x_embedding(rel_x_tokens)
        rel_y = self.rel_y_embedding(rel_y_tokens)
        re_xy = torch.concat([rel_x, rel_y], -1)
        xs = torch.einsum('b t d, b t t d -> b t d', self.embedding(xs), re_xy) + self.pos_embedding(order)
        xs = self.transformer_encoder(xs)
        xs = xs.reshape(-1, self.embedding_size*self.tf_max_len)
        xs = torch.tanh(self.fc1(xs))
        xs = self.fc2(xs)
        return xs


    # pe_blank = torch.zeros(128, position_dim, w_dim, h_dim, self.embedding_size)
    # (self.pos_encoder_3d, torch.full(position_indices.shape[0]1,-1), position_indices)
    # torch.vmap(torch.index_select)(self.pos_encoder_3d, torch.full((position_indices.shape[0],0),-1), position_indices)
    @staticmethod
    def add_to_argparse(parser):
        # parser.add_argument("--fc1", type=int, default=MB2016Transformer.DEFAULT_FC1_DIM)
        # parser.add_argument("--fc2", type=int, default=MB2016Transformer.DEFAULT_FC2_DIM)
        # parser.add_argument("--fc_dropout", type=float, default=MB2016Transformer.DEFAULT_FC_DROPOUT)
        return parser

    # def training_step(self, batch, batch_idx):
    #     xs, ys = batch  # unpack the batch
    #     xs = xs[:, 0]
    #     ys = ys.unsqueeze(1)
    #     preds = self(xs)  # apply the model
    #     loss = self.loss_fn(preds, y[:, 1:])
    #     loss = torch.nn.functional.mse_loss(outs, ys)  # compute the (squared error) loss
    #     self.log("train/loss", loss)
    #     outputs = {"loss": loss}
    #     return loss
    #
    # def validation_step(self: pl.LightningModule, batch: Tuple[torch.Tensor, torch.Tensor], batch_idx: int) -> torch.Tensor:
    #     xs, ys = batch  # unpack the batch
    #     xs = xs[:,0]
    #     ys = ys.unsqueeze(1)
    #     preds = self(xs)  # apply the model
    #     loss = torch.nn.functional.mse_loss(preds, ys)  # compute the (squared error) loss
    #     return loss
    #
    # def test_step(self: pl.LightningModule, batch: Tuple[torch.Tensor, torch.Tensor], batch_idx: int) -> torch.Tensor:
    #     xs, ys = batch  # unpack the batch
    #     xs = xs[:,0]
    #     ys = ys.unsqueeze(1)
    #     preds = self(xs)  # apply the model
    #     loss = torch.nn.functional.mse_loss(preds, ys)  # compute the (squared error) loss
    #     return loss

    def relative_to_absolute(self, q, x):
        """
        Converts the dimension that is specified from the axis
        from relative distances (with length 2*tokens-1) to absolute distance (length tokens)
          Input: [bs, heads, length, 2*length - 1]
          Output: [bs, heads, length, length]
        """
        b, l, device, dtype = *q.shape, q.device, q.dtype
        dd = {'device': device, 'dtype': dtype}
        col_pad = torch.zeros((b, l, 1), **dd)
        x = torch.cat((q, col_pad), dim=2)  # zero pad 2l-1 to 2l
        flat_x = rearrange(x, 'b l c -> b (l c)')
        flat_pad = torch.zeros((b, l - 1), **dd)
        flat_x_padded = torch.cat((flat_x, flat_pad), dim=2)
        final_x = flat_x_padded.reshape(b, l + 1, 2 * l - 1)
        final_x = final_x[:, :, :l, (l - 1):]
        return final_x


# from grade_predictor.data import MB2016
# from grade_predictor.data import base_data_module
# from grade_predictor.metadata import mb2016 as data_config
# if __name__ == "__main__":
#     base_dataset = base_data_moduleBaseDataModule()
#     dataset = MB2016()
#     dataset.prepare_data()
#     dataset.setup()
#     train_dataloader = dataset.train_dataloader()
#     val_dataloader = dataset.val_dataloader()
#     model = MB2016Transformer({
#         "input_dims": dataset.input_dims,
#         "output_dims": dataset.output_dims,
#         "token_dict_size": dataset.id_token_dict_size,
#         "max_sequence": dataset.max_sequence
#     })
#     trainer = pl.Trainer(fast_dev_run=True, accelerator="cpu")
#
#     trainer.fit(model, train_dataloader, val_dataloader)
