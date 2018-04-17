import os, sys
parentPath = os.path.abspath("..")
if parentPath not in sys.path:
    sys.path.insert(0,parentPath)

from random import shuffle
from network.policy_network import PolicyValNetwork_Giraffe
from network.value_network import CriticGiraffe
import chess.pgn
import chess.uci
# import random
import torch
from torch.autograd import Variable
from config import Config
from game.features import board_to_feature
from game.stockfish import Stockfish
from logger import Logger
import parallel_mcts_test
import policy_value_label_seq

#set the logger
logger = Logger('./logs')
model_pol = PolicyValNetwork_Giraffe(pretrain=False)
model_val = CriticGiraffe(pretrain = False)

def cross_entropy(pred, soft_targets):
    return torch.mean(torch.sum(- soft_targets.double() * torch.log(pred).double(), 1))


def get_board_position():
    pgn = open("kasparov.pgn")
    board_positions = []
    try:
        while True:
            kasgame = chess.pgn.read_game(pgn)
            if kasgame is None:
                break
            board = kasgame.board()
            board_positions.append(board.copy())
            for move in kasgame.main_line():
                board.push(move)
                board_positions.append(board.copy())
    except Exception:
        print("We have {} board positions".format(len(board_positions)))
        return board_positions

def save_trained_val(model_val, iteration_val):
    torch.save(model_val.state_dict(), "./{}_val.pt".format(iteration_val))

def save_trained_pol(model_pol, iteration_pol):
    torch.save(model_pol.state_dict(), "./{}_pol.pt".format(iteration_pol))


def pretrain(model_pol, model_val):
    iters_val = 0
    iters_pol = 0
    feature_batch_val = []
    feature_batch_pol = []
    targets_val_batch = []
    targets_pol_batch = []
    board_positions = get_board_position()
    shuffle(board_positions)
    print("Pretraining on {} board positions...".format(len(board_positions)))
    stockfish = Stockfish()

    for batch in range(Config.PRETRAIN_EPOCHS):
        for index, board_position in enumerate(board_positions):
            if (index + 1) % Config.minibatch_size != 0:
                feature_batch_val.append(board_to_feature(board_position))
                feature_batch_pol.append(board_to_feature(board_position))
                targets_val_batch.append(stockfish.stockfish_eval(board_position, 10))
                nvm, mind = policy_value_label_seq.value_policy(board_position)
                targets_pol_batch.append(mind)
            else:
                feature_batch_pol = torch.FloatTensor(feature_batch_pol)
                feature_batch_val = torch.FloatTensor(feature_batch_val)
                targets_val_batch = Variable(torch.FloatTensor(targets_val_batch))
                targets_pol_batch = Variable(torch.FloatTensor(targets_pol_batch))
                do_backprop_val(feature_batch_val, targets_val_batch, model_val, iters_val)
                do_backprop_pol(feature_batch_pol, targets_pol_batch, model_pol, iters_pol)
                iters_val = iters_val + 1
                iters_pol = iters_pol + 1
                feature_batch_pol = []
                feature_batch_val = []
                targets_val_batch = []
                targets_pol_batch = []
        print("Completed batch {} of {}".format(batch, Config.PRETRAIN_EPOCHS))


def do_backprop_val(batch_features, targets_val, model_val, iters_val):
    criterion1 = torch.nn.MSELoss(size_average=False)
    optimizer = torch.optim.Adam(model_val.parameters(), lr=1e-4)
    nn_val_out = model_val(batch_features)

    loss1 = criterion1(nn_val_out, targets_val)
    #loss2 = cross_entropy(nn_policy_out, targets_pol)

    l2_reg = None
    for weight in model_val.parameters():
        if l2_reg is None:
            l2_reg = weight.norm(2)
        else:
            l2_reg = l2_reg + weight.norm(2)
    loss3 = 0.1 * l2_reg

    loss = loss1.float() + loss3.float()
    print(iters_val)
    info = {
            'full_pt_loss1': loss1.data[0],
            'full_pt_loss3': loss3.data[0]
            }

    for tag, value in info.items():
        logger.scalar_summary(tag, value, iters_val)


    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    save_trained_val(model_val, iters_val)


def do_backprop_pol(batch_features, targets_pol, model_pol, iters_pol):
    optimizer = torch.optim.Adam(model_pol.parameters(), lr=1e-4)
    nn_policy_out, never_mind = model_pol(batch_features)
    loss2 = cross_entropy(nn_policy_out, targets_pol)
    loss = loss2.float()
    print("policy iters = ")
    print(iters_pol)
    info_pol = {
            '2net_pt_loss2': loss2.data[0]
            }

    for tag, value in info_pol.items():
        logger.scalar_summary(tag, value, iters_pol)

    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    save_trained_pol(model_pol, iters_pol)


pretrain(model_pol, model_val)
