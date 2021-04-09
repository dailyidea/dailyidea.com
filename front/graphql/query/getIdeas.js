export default `
query ideas($order: IdeaSortingOrder, $nextToken: String, $limit: Int) {
  ideas(order: $order, nextToken: $nextToken, limit: $limit) {
    items {
      userId
      authorAvatar
      ideaId
      shortId
      slug
      authorName
      authorSlug
      strippedContent
      content
      title
      createdDate
      ideaDate
      likesCount
      savesCount
      commentsCount
      visibility
    }
    nextToken
  }
}`
