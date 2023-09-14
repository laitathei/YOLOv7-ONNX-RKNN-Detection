import cv2
import time
import numpy as np

def xywh2xyxy(x):
    y = np.copy(x)
    y[..., 0] = x[..., 0] - x[..., 2] / 2  # top left x
    y[..., 1] = x[..., 1] - x[..., 3] / 2  # top left y
    y[..., 2] = x[..., 0] + x[..., 2] / 2  # bottom right x
    y[..., 3] = x[..., 1] + x[..., 3] / 2  # bottom right y
    return y

def clip_boxes(boxes, shape):
    boxes[..., [0, 2]] = boxes[..., [0, 2]].clip(0, shape[1])  # x1, x2
    boxes[..., [1, 3]] = boxes[..., [1, 3]].clip(0, shape[0])  # y1, y2

def scale_boxes(img1_shape, boxes, img0_shape, ratio_pad=None):
    # Rescale coords (xyxy) from img1_shape to img0_shape
    if ratio_pad is None:  # calculate from img0_shape
        gain = min(img1_shape[0] / img0_shape[0], img1_shape[1] / img0_shape[1])  # gain  = old / new
        pad = (img1_shape[1] - img0_shape[1] * gain) / 2, (img1_shape[0] - img0_shape[0] * gain) / 2  # wh padding
    else:
        gain = ratio_pad[0][0]
        pad = ratio_pad[1]

    boxes[:, [0, 2]] -= pad[0]  # x padding
    boxes[:, [1, 3]] -= pad[1]  # y padding
    boxes[:, :4] /= gain
    clip_boxes(boxes, img0_shape)
    return boxes

def nms(bboxes, scores, threshold=0.5):
    x1 = bboxes[:, 0]
    y1 = bboxes[:, 1]
    x2 = bboxes[:, 2]
    y2 = bboxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)

    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)

        if order.size == 1: break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, (xx2 - xx1))
        h = np.maximum(0.0, (yy2 - yy1))
        inter = w * h

        iou = inter / (areas[i] + areas[order[1:]] - inter)
        ids = np.where(iou <= threshold)[0]
        order = order[ids + 1]

    return keep

def non_max_suppression(prediction, conf_thres=0.25, iou_thres=0.45, classes=None, agnostic=False, multi_label=False,
                        labels=()):
    """Runs Non-Maximum Suppression (NMS) on inference results

    Returns:
         list of detections, on (n,6) tensor per image [xyxy, conf, cls]
    """

    bs = prediction.shape[0]              # batch size
    nc = prediction.shape[2] - 5  # number of classes
    xc = prediction[..., 4] > conf_thres  # candidates
    # Settings
    min_wh, max_wh = 2, 4096  # (pixels) minimum and maximum box width and height
    max_det = 300  # maximum number of detections per image
    max_nms = 30000  # maximum number of boxes into torchvision.ops.nms()
    time_limit = 10.0  # seconds to quit after
    redundant = True  # require redundant detections
    multi_label &= nc > 1  # multiple labels per box (adds 0.5ms/img)
    merge = False  # use merge-NMS

    t = time.time()
    output = [np.zeros((0,6))] * bs ## 【lulu】
    for xi, x in enumerate(prediction):  # image index, image inference
        # Apply constraints
        # x[((x[..., 2:4] < min_wh) | (x[..., 2:4] > max_wh)).any(1), 4] = 0  # width-height
        x = x[xc[xi]]  # confidence

        # If none remain process next image
        if not x.shape[0]:
            continue

        # Compute conf
        x[:, 5:] *= x[:, 4:5]  # conf = obj_conf * cls_conf

        # Box (center x, center y, width, height) to (x1, y1, x2, y2)
        box = xywh2xyxy(x[:, :4])

        # Detections matrix nx6 (xyxy, conf, cls)
        j = np.argmax(x[:, 5:], axis=1)  ## 【lulu】
        j = np.expand_dims(j, axis=1)
        conf = x[:, 5:].max(1, keepdims=True)
        x = np.concatenate([box, conf, j], axis=1)[conf.reshape(-1,) > conf_thres]

        # Check shape
        n = x.shape[0]  # number of boxes
        if not n:  # no boxes
            continue
        elif n > max_nms:  # excess boxes
            #x = x[x[:, 4].argsort(descending=True)[:max_nms]]  # sort by confidence
            x = x[np.argsort(x[:, 4])[::-1][:max_nms]]
        else:
            #x = x[x[:, 4].argsort(descending=True)]  # sort by confidence
            x = x[np.argsort(x[:, 4])[::-1]]

        # Batched NMS
        c = x[:, 5:6] * (0 if agnostic else max_wh)  # classes
        boxes, scores = x[:, :4] + c, x[:, 4]  # boxes (offset by class), scores
        i = nms(boxes, scores, iou_thres)  # NMS
        i = np.array(i)
        if i.shape[0] > max_det:  # limit detections
            i = i[:max_det]

        output[xi] = x[i]
        if (time.time() - t) > time_limit:
            break  # time limit exceeded

    return output

def letterbox(im, new_shape=(640, 640), color=(114, 114, 114), auto=True, scaleFill=False, scaleup=True, stride=32):
    # Resize and pad image while meeting stride-multiple constraints
    shape = im.shape[:2]  # current shape [height, width]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    # Scale ratio (new / old)
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    if not scaleup:  # only scale down, do not scale up (for better val mAP)
        r = min(r, 1.0)

    # Compute padding
    ratio = r, r  # width, height ratios
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]  # wh padding
    if auto:  # minimum rectangle
        dw, dh = np.mod(dw, stride), np.mod(dh, stride)  # wh padding
    elif scaleFill:  # stretch
        dw, dh = 0.0, 0.0
        new_unpad = (new_shape[1], new_shape[0])
        ratio = new_shape[1] / shape[1], new_shape[0] / shape[0]  # width, height ratios

    dw /= 2  # divide padding into 2 sides
    dh /= 2

    if shape[::-1] != new_unpad:  # resize
        im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    im = cv2.copyMakeBorder(im, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)  # add border
    return im, ratio, (dw, dh)

def preprocess(image, input_height, input_width):
    image_3c = image

    # Convert the image_3c color space from BGR to RGB
    image_3c = cv2.cvtColor(image_3c, cv2.COLOR_BGR2RGB)

    image_3c, ratio, dwdh = letterbox(image_3c, new_shape=[input_height, input_width], auto=False)

    # Normalize the image_3c data by dividing it by 255.0
    image_4c = np.array(image_3c) / 255.0

    # Transpose the image_3c to have the channel dimension as the first dimension
    image_4c = image_4c.transpose((2, 0, 1))

    # Expand the dimensions of the image_3c data to match the expected input shape
    image_4c = np.expand_dims(image_4c, axis=0).astype(np.float32)

    image_4c = np.ascontiguousarray(image_4c)  # contiguous
    
    return image_4c, image_3c

def postprocess(preds, img, orig_img, conf_thres, iou_thres, classes=None):
    p = non_max_suppression(preds[0], conf_thres, iou_thres)
    for i, pred in enumerate(p):  # per image
        shape = orig_img.shape
        results = []
        if not len(preds):
            results.append([[], []])  # save empty boxes
            continue
        # Rescale boxes from img_size to im0 size
        pred[:, :4] = scale_boxes(img.shape[2:], pred[:, :4], shape).round()
        results.append([pred[:, :6], shape[:2]])
    return results

def gen_color(class_num):
    color_list = []
    np.random.seed(1)
    while 1:
        a = list(map(int, np.random.choice(range(255),3)))
        if(np.sum(a)==0): continue
        color_list.append(a)
        if len(color_list)==class_num: break
    return color_list

def vis_result(image_3c, results, colorlist, CLASSES, result_path):
    boxes, shape = results
    # Convert the image_3c color space from BGR to RGB
    image_3c = cv2.cvtColor(image_3c, cv2.COLOR_RGB2BGR)
    vis_img = image_3c.copy()
    cls_list = []
    for i, box in enumerate (boxes):
        cls=int(box[-1])
        cls_list.append(cls)
        cv2.rectangle(vis_img, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (0,0,255),3,4)
        cv2.putText(vis_img, f"{CLASSES[cls]}:{round(box[4],2)}", (int(box[0]), int(box[1])), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    vis_img = np.concatenate([image_3c, vis_img],axis=1)
    for i in range (len(CLASSES)):
        num = cls_list.count(i)
        if num != 0:
            print(f"Found {num} {CLASSES[i]}")
    cv2.imwrite(f"./{result_path}/origin_image.jpg", image_3c)
    cv2.imwrite(f"./{result_path}/visual_image.jpg", vis_img)
    return vis_img
